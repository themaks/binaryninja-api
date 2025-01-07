# Copyright (c) 2015-2024 Vector 35 Inc
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

import ctypes
import traceback

# Binary Ninja components
import binaryninja
from . import _binaryninjacore as core, LinearDisassemblyLine
from .enums import LinearDisassemblyLineType
from . import binaryview
from . import types
from .log import log_error
from typing import Iterable, List, Optional, Union, Tuple


class _RenderLayerMetaclass(type):
	def __iter__(self):
		binaryninja._init_plugins()
		count = ctypes.c_ulonglong()
		types = core.BNGetRenderLayerList(count)
		try:
			for i in range(0, count.value):
				yield CoreRenderLayer(types[i])
		finally:
			core.BNFreeRenderLayerList(types)

	def __getitem__(self, value):
		binaryninja._init_plugins()
		handle = core.BNGetRenderLayerByName(str(value))
		if handle is None:
			raise KeyError(f"'{value}' is not a valid RenderLayer")
		return CoreRenderLayer(handle)


class BaseRenderLayer(metaclass=_RenderLayerMetaclass):
	"""
	BaseRenderLayer provides a lower-level interface for manipulating graphs
	and lines directly, whereas :py:class:`RenderLayer` provides an interface where you
	can choose to target a specific IL level or a couple different Linear View specific
	line constructs.
	"""

	name = None
	_registered_layers = []
	_pending_lines = {}

	def __init__(self, handle=None):
		if handle is not None:
			self.handle = core.handle_of_type(handle, core.BNRenderLayer)
			self.__dict__["name"] = core.BNGetRenderLayerName(handle)
		else:
			self.handle = None

	@classmethod
	def register(cls):
		"""
		Register a custom Render Layer.
		"""
		layer = cls()

		assert layer.__class__.name is not None
		assert layer.handle is None

		layer._cb = core.BNRenderLayerCallbacks()
		layer._cb.context = 0
		layer._cb.applyToFlowGraph = layer._cb.applyToFlowGraph.__class__(layer._apply_to_flow_graph)
		layer._cb.applyToLinearViewObject = layer._cb.applyToLinearViewObject.__class__(layer._apply_to_linear_view_object)
		layer._cb.freeLines = layer._cb.freeLines.__class__(layer._free_lines)
		layer.handle = core.BNRegisterRenderLayer(cls.name, layer._cb)
		cls._registered_layers.append(layer)

	def __eq__(self, other):
		if not isinstance(other, BaseRenderLayer):
			return False
		return self.name == other.name

	def __str__(self):
		return f'<RenderLayer: {self.name}>'

	def __repr__(self):
		return f'<RenderLayer: {self.name}>'

	def _apply_to_flow_graph(self, ctxt, graph):
		try:
			self.apply_to_flow_graph(binaryninja.FlowGraph(handle=core.BNNewFlowGraphReference(graph)))
		except:
			log_error(traceback.format_exc())

	def _apply_to_linear_view_object(self, ctxt, obj, prev, next, in_lines, in_line_count, out_lines, out_line_count):
		try:
			obj_obj = binaryninja.LinearViewObject(core.BNNewLinearViewObjectReference(obj))
			prev_obj = binaryninja.LinearViewObject(core.BNNewLinearViewObjectReference(prev)) if prev else None
			next_obj = binaryninja.LinearViewObject(core.BNNewLinearViewObjectReference(next)) if next else None

			lines = []
			for i in range(in_line_count):
				lines.append(LinearDisassemblyLine._from_core_struct(in_lines[i], obj=obj_obj))

			lines = self.apply_to_linear_view_object(obj_obj, prev_obj, next_obj, lines)

			out_line_count[0] = len(lines)
			out_lines_buf = (core.BNLinearDisassemblyLine * len(lines))()
			for i, r in enumerate(lines):
				out_lines_buf[i] = r._to_core_struct()
			out_lines_ptr = ctypes.cast(out_lines_buf, ctypes.c_void_p)
			out_lines[0] = out_lines_buf
			self._pending_lines[out_lines_ptr.value] = (out_lines_ptr.value, out_lines_buf)
		except:
			log_error(traceback.format_exc())
			out_lines[0] = None
			out_line_count[0] = 0

	def _free_lines(self, ctxt, lines, count):
		try:
			buf = ctypes.cast(lines, ctypes.c_void_p)
			if buf.value is not None:
				if buf.value not in self._pending_lines:
					raise ValueError("freeing lines list that wasn't allocated")
				del self._pending_lines[buf.value]
		except:
			log_error(traceback.format_exc())

	def apply_to_flow_graph(self, graph: 'binaryninja.FlowGraph') -> None:
		"""
		Apply this Render Layer to a Flow Graph, potentially modifying its nodes,
		their edges, their lines, and their lines' content.

		:param graph: Graph to modify
		"""
		pass

	def apply_to_linear_view_object(
			self,
			obj: 'binaryninja.LinearViewObject',
			prev: Optional['binaryninja.LinearViewObject'],
			next: Optional['binaryninja.LinearViewObject'],
			lines: List['binaryninja.LinearDisassemblyLine']
	) -> List['binaryninja.LinearDisassemblyLine']:
		"""
		Apply this Render Layer to the lines produced by a LinearViewObject for rendering
		in Linear View, potentially modifying the lines and their contents.

		:param obj: Linear View Object being rendered
		:param prev: Linear View Object located directly above this one
		:param next: Linear View Object located directly below this one
		:param lines: Lines originally rendered by the Linear View Object
		:return: Updated set of lines to display in Linear View
		"""
		return lines


class CoreRenderLayer(BaseRenderLayer):

	def apply_to_flow_graph(self, graph: 'binaryninja.FlowGraph') -> None:
		core.BNApplyRenderLayerToFlowGraph(self.handle, graph.handle)

	def apply_to_linear_view_object(
			self,
			obj: 'binaryninja.LinearViewObject',
			prev: Optional['binaryninja.LinearViewObject'],
			next: Optional['binaryninja.LinearViewObject'],
			lines: List['binaryninja.LinearDisassemblyLine']
	) -> List['binaryninja.LinearDisassemblyLine']:

		in_lines_buf = (core.BNLinearDisassemblyLine * len(lines))()
		for i, r in enumerate(lines):
			in_lines_buf[i] = r._to_core_struct()

		out_lines = ctypes.POINTER(core.BNLinearDisassemblyLine)()
		out_line_count = ctypes.c_size_t(0)

		core.BNApplyRenderLayerToLinearViewObject(
			self.handle,
			obj.handle,
			prev.handle if prev is not None else None,
			next.handle if next is not None else None,
			in_lines_buf,
			len(lines),
			out_lines,
			out_line_count
		)

		result = []
		for i in range(out_line_count.value):
			result.append(binaryninja.LinearDisassemblyLine._from_core_struct(out_lines[i], obj=obj))

		core.BNFreeLinearDisassemblyLines(out_lines, out_line_count.value)

		return result


class RenderLayer(BaseRenderLayer):
	"""
	RenderLayer is a plugin class that allows you to customize the presentation of
	Linear and Graph view output, adding, changing, or removing lines before they are
	presented in the UI.

	BaseRenderLayer provides a lower-level interface for manipulating the graphs
	and lines directly, whereas RenderLayer provides an interface where you can
	choose to target a specific IL level or a couple different Linear View specific
	line constructs.
	"""

	def apply_to_disassembly_block(
			self,
			block: 'binaryninja.BasicBlock',
			lines: List['binaryninja.DisassemblyTextLine']
	):
		"""
		Apply this Render Layer to a single Basic Block of Disassembly lines.
		Subclasses should modify the input `lines` list to make modifications to
		the presentation of the block.

		.. note:: This function will only handle Disassembly lines, and not any ILs.

		:param block: Basic Block containing those lines
		:param lines: Lines of text for the block, to be modified by this function
		"""
		pass

	def apply_to_low_level_il_block(
			self,
			block: 'binaryninja.LowLevelILBasicBlock',
			lines: List['binaryninja.DisassemblyTextLine']
	):
		"""
		Apply this Render Layer to a single Basic Block of Low Level IL lines.
		Subclasses should modify the input `lines` list to make modifications to
		the presentation of the block.

		.. note:: This function will only handle Lifted IL/LLIL/LLIL(SSA) lines. \
		You can use the block's `function_graph_type` property to determine which is being handled.

		:param block: Basic Block containing those lines
		:param lines: Lines of text for the block, to be modified by this function
		"""
		pass

	def apply_to_medium_level_il_block(
			self,
			block: 'binaryninja.MediumLevelILBasicBlock',
			lines: List['binaryninja.DisassemblyTextLine']
	):
		"""
		Apply this Render Layer to a single Basic Block of Medium Level IL lines.
		Subclasses should modify the input `lines` list to make modifications to
		the presentation of the block.

		.. note:: This function will only handle MLIL/MLIL(SSA)/Mapped MLIL/Mapped MLIL(SSA) lines. \
		You can use the block's `function_graph_type` property to determine which is being handled.

		:param block: Basic Block containing those lines
		:param lines: Lines of text for the block, to be modified by this function
		"""
		pass

	def apply_to_high_level_il_block(
			self,
			block: 'binaryninja.HighLevelILBasicBlock',
			lines: List['binaryninja.DisassemblyTextLine']
	):
		"""
		Apply this Render Layer to a single Basic Block of High Level IL lines.
		Subclasses should modify the input `lines` list to make modifications to
		the presentation of the block.

		.. note:: This function will only handle HLIL/HLIL(SSA)/Language Representation lines. \
		You can use the block's `function_graph_type` property to determine which is being handled.

		.. warning:: This function will NOT apply to High Level IL bodies as displayed \
		in Linear View! Those are handled by `apply_to_hlil_body` instead as they \
		do not have a Basic Block associated with them.

		:param block: Basic Block containing those lines
		:param lines: Lines of text for the block, to be modified by this function
		"""
		pass

	def apply_to_hlil_body(
			self,
			function: 'binaryninja.Function',
			lines: List['binaryninja.LinearDisassemblyLine']
	):
		"""
		Apply this Render Layer to the entire body of a High Level IL function.
		Subclasses should modify the input `lines` list to make modifications to
		the presentation of the function.

		.. warning:: This function only applies to Linear View, and not to Graph View! \
		If you want to handle Graph View too, you will need to use `apply_to_high_level_il_block` \
		and handle the lines one block at a time.

		:param function: Function containing those lines
		:param lines: Lines of text for the function, to be modified by this function
		"""
		pass

	def apply_to_misc_linear_lines(
			self,
			obj: 'binaryninja.LinearViewObject',
			prev: Optional['binaryninja.LinearViewObject'],
			next: Optional['binaryninja.LinearViewObject'],
			lines: List['binaryninja.LinearDisassemblyLine']
	):
		"""
		Apply to lines generated by Linear View that are not part of a function.
		It is up to your implementation to figure out which type of Linear View Object
		lines these are, and what to do with them.

		:param obj: Linear View Object being rendered
		:param prev: Linear View Object located directly above this one
		:param next: Linear View Object located directly below this one
		:param lines: Lines rendered by `obj`, to be modified by this functino
		"""
		pass

	def apply_to_block(
			self,
			block: 'binaryninja.BasicBlock',
			lines: List['binaryninja.DisassemblyTextLine'],
	):
		"""
		Apply to lines generated by a Basic Block, of any type. If not overriden, this
		function will call the appropriate apply_to_X_level_il_block function.

		:param block: Basic Block containing those lines
		:param lines: Lines of text for the block, to be modified by this function
		"""
		if not block.is_il:
			self.apply_to_disassembly_block(block, lines)
		elif block.is_low_level_il:
			self.apply_to_low_level_il_block(block, lines)
		elif block.is_medium_level_il:
			self.apply_to_medium_level_il_block(block, lines)
		elif block.is_high_level_il:
			self.apply_to_high_level_il_block(block, lines)
		else:
			# ???
			pass

	def apply_to_flow_graph(self, graph: 'binaryninja.FlowGraph') -> None:
		"""
		Overridden from BaseRenderLayer to provide more specific callbacks. Check
		:py:func:`BaseRenderLayer.apply_to_flow_graph` in case you want to
		override this directly.

		:param graph: Graph to modify
		"""
		for i, node in enumerate(graph.nodes):
			lines = node.lines
			if node.basic_block is not None and isinstance(node.basic_block, binaryninja.BasicBlock):
				self.apply_to_block(node.basic_block, lines)
			node.lines = lines

	def apply_to_linear_view_object(
			self,
			obj: 'binaryninja.LinearViewObject',
			prev: Optional['binaryninja.LinearViewObject'],
			next: Optional['binaryninja.LinearViewObject'],
			lines: List['binaryninja.LinearDisassemblyLine']
	) -> List['binaryninja.LinearDisassemblyLine']:
		"""
		Overridden from BaseRenderLayer to provide more specific callbacks. Check
		:py:func:`BaseRenderLayer.apply_to_linear_view_object` in case you want to
		override this directly.

		:param obj: Linear View Object being rendered
		:param prev: Linear View Object located directly above this one
		:param next: Linear View Object located directly below this one
		:param lines: Lines originally rendered by the Linear View Object
		:return: Updated set of lines to display in Linear View
		"""
		# Hack: HLIL bodies don't have basic blocks
		if obj.identifier.name in [
			"HLIL Function Body",
			"HLIL SSA Function Body",
			"Language Representation Function Body"
		]:
			self.apply_to_hlil_body(lines[0].function, lines)
			return lines

		block_lines = []
		final_lines = []
		last_block = None
		for line in lines:
			# Assume we've finished a block when the line's block changes
			if line.block != last_block:
				if len(block_lines) > 0:
					if last_block is not None:
						# Convert linear lines to disassembly lines for the apply()
						# and then convert back for linear view
						disasm_lines = [line.contents for line in block_lines]
						disasm_map = {id(line.contents): line for line in block_lines}
						self.apply_to_block(last_block, disasm_lines)
						block_lines = [
							LinearDisassemblyLine(
								disasm_map[id(contents)].type if id(contents) in disasm_map else LinearDisassemblyLineType.CodeDisassemblyLineType,
								block_lines[0].function,
								block_lines[0].block,
								contents
							) for contents in disasm_lines
						]
					else:
						self.apply_to_misc_linear_lines(obj, prev, next, block_lines)
				last_block = line.block
				final_lines += block_lines
				block_lines = []
			block_lines.append(line)

		# And we've finished a block when we're done with every line
		if len(block_lines) > 0:
			if last_block is not None:
				# Convert linear lines to disassembly lines for the apply()
				# and then convert back for linear view
				disasm_lines = [line.contents for line in block_lines]
				disasm_map = {id(line.contents): line for line in block_lines}
				self.apply_to_block(last_block, disasm_lines)
				block_lines = [
					LinearDisassemblyLine(
						disasm_map[id(contents)].type if id(contents) in disasm_map else LinearDisassemblyLineType.CodeDisassemblyLineType,
						block_lines[0].function,
						block_lines[0].block,
						contents
					) for contents in disasm_lines
				]
			else:
				self.apply_to_misc_linear_lines(obj, prev, next, block_lines)
		final_lines += block_lines
		return final_lines
