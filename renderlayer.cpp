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
		obj ? new LinearViewObject(BNNewLinearViewObjectReference(obj)) : nullptr,
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
		obj ? obj->GetObject() : nullptr,
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
