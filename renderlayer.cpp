// Copyright (c) 2015-2024 Vector 35 Inc
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to
// deal in the Software without restriction, including without limitation the
// rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
// sell copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
// IN THE SOFTWARE.

#include "binaryninjaapi.h"
#include "ffi.h"

using namespace BinaryNinja;
using namespace std;

RenderLayer::RenderLayer(const std::string& name): m_nameForRegister(name)
{

}


RenderLayer::RenderLayer(BNRenderLayer* layer)
{
	m_object = layer;
}


void RenderLayer::ApplyToFlowGraphCallback(void* ctxt, BNFlowGraph* graph)
{
	RenderLayer* layer = (RenderLayer*)ctxt;
	layer->ApplyToFlowGraph(new CoreFlowGraph(BNNewFlowGraphReference(graph)));
}


void RenderLayer::ApplyToLinearViewObjectCallback(
	void* ctxt,
	BNLinearViewObject* obj,
	BNLinearViewObject* prev,
	BNLinearViewObject* next,
	BNLinearDisassemblyLine* inLines,
	size_t inLineCount,
	BNLinearDisassemblyLine** outLines,
	size_t* outLineCount
)
{
	RenderLayer* layer = (RenderLayer*)ctxt;
	vector<LinearDisassemblyLine> lines = ParseAPIObjectList<LinearDisassemblyLine>(inLines, inLineCount);

	layer->ApplyToLinearViewObject(
		new LinearViewObject(BNNewLinearViewObjectReference(obj)),
		prev ? new LinearViewObject(BNNewLinearViewObjectReference(prev)) : nullptr,
		next ? new LinearViewObject(BNNewLinearViewObjectReference(next)) : nullptr,
		lines
	);

	AllocAPIObjectList<LinearDisassemblyLine>(lines, outLines, outLineCount);
}


void RenderLayer::FreeLinesCallback(void* ctxt, BNLinearDisassemblyLine* lines, size_t count)
{
	FreeAPIObjectList<LinearDisassemblyLine>(lines, count);
}


void RenderLayer::Register(RenderLayer* layer)
{
	BNRenderLayerCallbacks cb;
	cb.context = (void*)layer;
	cb.applyToFlowGraph = ApplyToFlowGraphCallback;
	cb.applyToLinearViewObject = ApplyToLinearViewObjectCallback;
	cb.freeLines = FreeLinesCallback;
	layer->m_object = BNRegisterRenderLayer(layer->m_nameForRegister.c_str(), &cb);
}


std::vector<Ref<RenderLayer>> RenderLayer::GetList()
{
	size_t count;
	BNRenderLayer** list = BNGetRenderLayerList(&count);
	vector<Ref<RenderLayer>> result;
	for (size_t i = 0; i < count; i ++)
		result.push_back(new CoreRenderLayer(list[i]));
	BNFreeRenderLayerList(list);
	return result;
}


Ref<RenderLayer> RenderLayer::GetByName(const std::string& name)
{
	BNRenderLayer* result = BNGetRenderLayerByName(name.c_str());
	if (!result)
		return nullptr;
	return new CoreRenderLayer(result);
}


std::string RenderLayer::GetName() const
{
	char* name = BNGetRenderLayerName(m_object);
	std::string value = name;
	BNFreeString(name);
	return value;
}


void RenderLayer::ApplyToBlock(
	Ref<BasicBlock> block,
	std::vector<DisassemblyTextLine>& lines
)
{
	if (!block->IsILBlock())
	{
		ApplyToDisassemblyBlock(block, lines);
	}
	else if (block->IsLowLevelILBlock())
	{
		ApplyToLowLevelILBlock(block, lines);
	}
	else if (block->IsMediumLevelILBlock())
	{
		ApplyToMediumLevelILBlock(block, lines);
	}
	else if (block->IsHighLevelILBlock())
	{
		ApplyToHighLevelILBlock(block, lines);
	}
}


void RenderLayer::ApplyToFlowGraph(Ref<FlowGraph> graph)
{
	for (auto node: graph->GetNodes())
	{
		auto lines = node->GetLines();
		if (node->GetBasicBlock())
		{
			ApplyToBlock(node->GetBasicBlock(), lines);
		}
		node->SetLines(lines);
	}
}


void RenderLayer::ApplyToLinearViewObject(
	Ref<LinearViewObject> obj,
	Ref<LinearViewObject> prev,
	Ref<LinearViewObject> next,
	std::vector<LinearDisassemblyLine>& lines
)
{
	// Hack: HLIL bodies don't have basic blocks
	if (!lines.empty() &&
		(obj->GetIdentifier().name == "HLIL Function Body"
		|| obj->GetIdentifier().name == "HLIL SSA Function Body"
		|| obj->GetIdentifier().name == "Language Representation Function Body"))
	{
		ApplyToHighLevelILBody(lines[0].function, lines);
		return;
	}

	std::vector<LinearDisassemblyLine> blockLines;
	std::vector<LinearDisassemblyLine> finalLines;
	Ref<BasicBlock> lastBlock;

	for (auto& line: lines)
	{
		// Assume we've finished a block when the line's block changes
		if (line.block != lastBlock)
		{
			if (!blockLines.empty())
			{
				if (lastBlock)
				{
					// Convert linear lines to disassembly lines for the apply()
					// and then convert back for linear view
					std::vector<DisassemblyTextLine> disasmLines;
					for (auto& blockLine: blockLines)
					{
						disasmLines.push_back(blockLine.contents);
					}
					ApplyToBlock(lastBlock, disasmLines);

					Ref<BasicBlock> block = blockLines[0].block;
					Ref<Function> func = blockLines[0].function;
					blockLines.clear();
					for (auto& blockLine: disasmLines)
					{
						LinearDisassemblyLine newLine;
						// todo: losing this information (might not matter)
						newLine.type = CodeDisassemblyLineType;
						newLine.block = block;
						newLine.function = func;
						newLine.contents = blockLine;
						blockLines.push_back(newLine);
					}
				}
				else
				{
					ApplyToMiscLinearLines(obj, prev, next, blockLines);
				}
			}
			lastBlock = line.block;
			std::move(blockLines.begin(), blockLines.end(), std::back_inserter(finalLines));
		}
		blockLines.push_back(line);
	}
	// And we've finished a block when we're done with every line
	if (!blockLines.empty())
	{
		if (lastBlock)
		{
			// Convert linear lines to disassembly lines for the apply()
			// and then convert back for linear view
			std::vector<DisassemblyTextLine> disasmLines;
			for (auto& blockLine: blockLines)
			{
				disasmLines.push_back(blockLine.contents);
			}
			ApplyToBlock(lastBlock, disasmLines);

			Ref<BasicBlock> block = blockLines[0].block;
			Ref<Function> func = blockLines[0].function;
			blockLines.clear();
			for (auto& blockLine: disasmLines)
			{
				LinearDisassemblyLine newLine;
				// todo: losing this information (might not matter)
				newLine.type = CodeDisassemblyLineType;
				newLine.block = block;
				newLine.function = func;
				newLine.contents = blockLine;
				blockLines.push_back(newLine);
			}
		}
		else
		{
			ApplyToMiscLinearLines(obj, prev, next, blockLines);
		}
	}
	std::move(blockLines.begin(), blockLines.end(), std::back_inserter(finalLines));

	lines = finalLines;
}


CoreRenderLayer::CoreRenderLayer(BNRenderLayer* layer): RenderLayer(layer)
{
}


void CoreRenderLayer::ApplyToFlowGraph(Ref<FlowGraph> graph)
{
	BNApplyRenderLayerToFlowGraph(m_object, graph->GetObject());
}


void CoreRenderLayer::ApplyToLinearViewObject(
	Ref<LinearViewObject> obj,
	Ref<LinearViewObject> prev,
	Ref<LinearViewObject> next,
	std::vector<LinearDisassemblyLine>& lines
)
{
	BNLinearDisassemblyLine* inLines;
	size_t inLineCount;
	AllocAPIObjectList<LinearDisassemblyLine>(lines, &inLines, &inLineCount);

	BNLinearDisassemblyLine* outLines;
	size_t outLineCount;

	BNApplyRenderLayerToLinearViewObject(
		m_object,
		obj->GetObject(),
		prev ? prev->GetObject() : nullptr,
		next ? next->GetObject() : nullptr,
		inLines,
		inLineCount,
		&outLines,
		&outLineCount
	);

	lines = ParseAPIObjectList<LinearDisassemblyLine>(outLines, outLineCount);
	FreeAPIObjectList<LinearDisassemblyLine>(inLines, inLineCount);
}
