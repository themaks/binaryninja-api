import functools
from typing import List, Mapping, Tuple, Iterator

from binaryninja import DisassemblyTextLine, LinearDisassemblyLineType, Function, \
    LowLevelILInstruction, TypeClass, DisassemblyTextRenderer, MediumLevelILFunction, \
    MediumLevelILCallSsa, MediumLevelILVarSsa, MediumLevelILConstBase, \
    MediumLevelILInstruction, MediumLevelILTailcallSsa, MediumLevelILOperation, \
    MediumLevelILVarPhi, log_debug
from binaryninja import RenderLayer, BasicBlock, InstructionTextTokenType, FlowGraph, \
    LinearViewObject, LinearDisassemblyLine

"""
Render Layer that shows you where the arguments to calls are set.

But how do you determine the argument to a call?
What seems like it has worked:
- You can't determine that an instruction is a parameter, you have to go from the call to its parameters
- Since trying to look up the call for an instruction is impossible, instead go through every call at once for a function (and memoize it)
- LLIL is useless for looking this up, since it has no types and the call parameters often include a list of every register
- Using MLIL, we can find all of the parameters as MLIL instructions, but we need to map them to LLIL so we can use them in the LLIL/Disasm display
- How do we map them? Turns out that's rather inconvenient:
  - Register arguments are generally pretty easy because they are just MLIL vars
  - Stack arguments somehow also work out generally, the .llil on the MLIL points to the push()
  - Constants are a mess and I just use the MLIL's address (this is often incorrect)
  - Flags are completely unhandled for now
  - Phis are handled by just looking up every var they use... probably not proper but sort of works
- This fails in a couple of scenarios though, notably __builtin_xxxxxx() functions
  - Which instruction specifies the length of a group of `mov qword [rbx+8], rax {0}` calls? I think it just picks one?
  - The `rep` instructions could actually have these params resolved (they use real registers) but in practice this doesn't work
  - Thunks are unhandled
"""

@functools.lru_cache(maxsize=64)
def get_param_sites(mlil: MediumLevelILFunction) -> Mapping[LowLevelILInstruction, List[Tuple[MediumLevelILInstruction, int]]]:
    """
    For a given function, find all LLIL instructions that are parameters to a call,
    and return a mapping for each instruction with all the calls that it maps to,
    their corresponding MLIL call instruction, and which numbered parameter they are
    in the call.

    :param mlil: MLIL function to search
    :return: Map of param sites as described above
    """
    call_sites = {}
    mlil = mlil.ssa_form

    # As a function to handle call and tailcall identically
    def collect_call_params(call_site, dest, params):
        def_sites = []
        for i, param in enumerate(params):
            llil = param.llil
            if llil is not None:
                def_sites.append((param, llil))
                continue

            match param:
                case MediumLevelILVarSsa(src=var_src):
                    def_site = mlil.get_ssa_var_definition(var_src)
                    if def_site is not None and def_site.llil is not None:
                        def_sites.append((i, def_site.llil))
                        continue
                    # Handle phis by just looking up the def sites of all their sources
                    match def_site:
                        case MediumLevelILVarPhi(src=phis):
                            for phi in phis:
                                phi_def = mlil.get_ssa_var_definition(phi)
                                if phi_def is not None and phi_def.llil is not None:
                                    def_sites.append((i, phi_def.llil))
                case MediumLevelILConstBase():
                    # This is wrong, but it works (sometimes)
                    # Oh god, have I just quoted php.net
                    def_site_idx = mlil.llil.get_instruction_start(param.address)
                    if def_site_idx is not None:
                        def_sites.append((i, mlil.llil[def_site_idx].ssa_form))
                        continue

            if len(def_sites) == 0:
                log_debug(f"Could not find def site for param {i} in call at {call_site.address:#x}")

        call_sites[call_site] = def_sites

    for instr in mlil.instructions:
        match instr:
            case MediumLevelILCallSsa(dest=dest, params=params) as call_site:
                collect_call_params(call_site, dest, params)
            case MediumLevelILTailcallSsa(dest=dest, params=params) as call_site:
                collect_call_params(call_site, dest, params)

    # Inverse args
    all_def_sites = {}
    for call_site, params in call_sites.items():
        for (param_idx, llil) in params:
            if llil not in all_def_sites:
                all_def_sites[llil] = []
            else:
                print(f"got two at {llil.instr_index} @ {llil.address:#x} -> {call_site.address:#x}")
            all_def_sites[llil].append((call_site, param_idx))

    return all_def_sites


def get_llil_arg(llil: LowLevelILInstruction) -> Iterator[Tuple[str, MediumLevelILInstruction]]:
    args = get_param_sites(llil.function.mlil)

    if llil.ssa_form in args:
        for call_site, param_idx in args[llil.ssa_form]:
            target_type = call_site.function.get_expr_type(call_site.dest.expr_index)

            # Try getting the param name from the call's type
            if target_type is not None:
                if target_type.type_class == TypeClass.PointerTypeClass:
                    target_type = target_type.target
                if target_type.type_class == TypeClass.FunctionTypeClass:
                    target_params = target_type.parameters
                    if param_idx < len(target_params):
                        param_name = target_params[param_idx].name
                        if param_name == '':
                            param_name = f"arg{param_idx+1}"
                        yield param_name, call_site
                        continue

            # Some calls have extra params that aren't reflected in their type
            yield f"arg{param_idx+1}", call_site
    return


class ArgumentsRenderLayer(RenderLayer):
    name = "Annotate Call Parameters"

    def apply_to_disassembly_block(
            self,
            block: BasicBlock,
            lines: List['DisassemblyTextLine']
    ):
        renderer = DisassemblyTextRenderer(block.function)
        skip_lines = []
        for i, line in enumerate(lines):
            if len(line.tokens) == 0:
                continue
            if i in skip_lines:
                continue
            llil_instr = block.function.get_llil_at(line.address)
            if llil_instr is not None:
                new_lines = []
                for (arg, call) in get_llil_arg(llil_instr):
                    if call.operation == MediumLevelILOperation.MLIL_TAILCALL_SSA:
                        comment = f"Argument '{arg}' for tailcall at {call.address:#x}"
                    else:
                        comment = f"Argument '{arg}' for call at {call.address:#x}"
                    renderer.wrap_comment(new_lines, line, comment, False, "  ",  "")
                    for j, token in enumerate(line.tokens):
                        if token.type == InstructionTextTokenType.AddressSeparatorToken:
                            line.tokens = line.tokens[:j]
                            break

                if len(new_lines) > 0:
                    lines.pop(i)
                    for j, new_line in enumerate(new_lines):
                        lines.insert(i + j, new_line)
                        skip_lines.append(i + j)

    def apply_to_low_level_il_block(
            self,
            block: BasicBlock,
            lines: List['DisassemblyTextLine']
    ):
        renderer = DisassemblyTextRenderer(block.function)
        skip_lines = []
        for i, line in enumerate(lines):
            if len(line.tokens) == 0:
                continue
            if i in skip_lines:
                continue
            if line.il_instruction is not None:
                new_lines = []
                for (arg, call) in get_llil_arg(line.il_instruction):
                    if call.operation == MediumLevelILOperation.MLIL_TAILCALL_SSA:
                        comment = f"Argument '{arg}' for tailcall at {call.address:#x}"
                    else:
                        comment = f"Argument '{arg}' for call at {call.address:#x}"
                    renderer.wrap_comment(new_lines, line, comment, False, "  ", "")
                    for j, token in enumerate(line.tokens):
                        if token.type == InstructionTextTokenType.AddressSeparatorToken:
                            line.tokens = line.tokens[:j]
                            break

                if len(new_lines) > 0:
                    lines.pop(i)
                    for j, new_line in enumerate(new_lines):
                        lines.insert(i + j, new_line)
                        skip_lines.append(i + j)


ArgumentsRenderLayer.register()
