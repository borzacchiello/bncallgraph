from binaryninja import (
	DisassemblyTextLine,
	InstructionTextToken,
	InstructionTextTokenType,
	FlowGraph,
	FlowGraphNode,
	BranchType,
	enums,
	PluginCommand,
	Settings,
	BackgroundTaskThread
)

Settings().register_group("bn-callgraph", "BN CallGraph")
Settings().register_setting("bn-callgraph.showColorRoot", """
	{
		"title" : "Colorize Root",
		"type" : "boolean",
		"default" : true,
		"description" : "Show root node in green"
	}
	""")
Settings().register_setting("bn-callgraph.showColorLeaves", """
	{
		"title" : "Colorize Leaves",
		"type" : "boolean",
		"default" : true,
		"description" : "Show leaves node in red"
	}
	""")
Settings().register_setting("bn-callgraph.showIndirectCalls", """
	{
		"title" : "Show Indirect Calls",
		"type" : "boolean",
		"default" : true,
		"description" : "Show indirect calls as undetermined nodes in the graph"
	}
	""")

class UndeterminedFunction(object):
	id_num = 0

	def __init__(self, addr):
		self.id = UndeterminedFunction.id_num
		self.start = addr
		self.name  = "UndFunction_%d" % self.id

		UndeterminedFunction.id_num += 1

	def __hash__(self):
		return hash("und_%d" % self.id)

	def __eq__(self, other):
		return isinstance(other, UndeterminedFunction) and self.id == other.id

class ExternalFunction(object):
	def __init__(self, name):
		self.start = 0
		self.name  = "Ext_" + name

	def __hash__(self):
		return hash(self.name)

	def __eq__(self, other):
		return isinstance(other, ExternalFunction) and self.name == other.name

class GraphWrapper(object):
	def __init__(self, root_function):
		self.nodes = {}
		self.edges = set()
		self.graph = FlowGraph()
		self.root_function = root_function
		root_node = FlowGraphNode(self.graph)
		if Settings().get_bool("bn-callgraph.showColorRoot"):
			root_node.highlight = enums.HighlightStandardColor.GreenHighlightColor
		root_node.lines = [
			GraphWrapper._build_function_text(root_function)
		]
		self.graph.append(root_node)
		self.nodes[root_function] = root_node

	@staticmethod
	def _build_function_text(function):
		res = \
			DisassemblyTextLine ([
					InstructionTextToken(
						InstructionTextTokenType.AddressDisplayToken,
						"{:#x}".format(function.start),
						value=function.start,
					),
					InstructionTextToken(
						InstructionTextTokenType.OperandSeparatorToken,
						" @ "
					),
					InstructionTextToken(
						InstructionTextTokenType.CodeSymbolToken,
						function.name,
						function.start
					)
				])
		return res

	def add(self, function, father_function):
		assert father_function in self.nodes
		if (father_function, function) in self.edges:
			return

		if function in self.nodes:
			node = self.nodes[function]
		else:
			node = FlowGraphNode(self.graph)
			node.lines = [
				GraphWrapper._build_function_text(function)
			]
			self.graph.append(node)
			self.nodes[function] = node

		father = self.nodes[father_function]
		father.add_outgoing_edge(
			BranchType.UnconditionalBranch,
			node
		)
		self.edges.add(
			(father_function, function)
		)

	def show(self):
		if Settings().get_bool("bn-callgraph.showColorLeaves"):
			nodes_dst = set([edge[1] for edge in self.edges])
			nodes_src = set([edge[0] for edge in self.edges])

			leaves = nodes_dst - nodes_src
			for leave in leaves:
				self.nodes[leave].highlight = enums.HighlightStandardColor.RedHighlightColor
		if Settings().get_bool("bn-callgraph.showIndirectCalls"):
			for fun in self.nodes:
				if isinstance(fun, UndeterminedFunction):
					self.nodes[fun].highlight = enums.HighlightStandardColor.BlueHighlightColor

		self.graph.show("Callgraph starting from {}".format(self.root_function.name))

def callgraph(bv, current_function):
	bv.update_analysis_and_wait()
	graph = GraphWrapper(current_function)

	show_indirect = False
	if Settings().get_bool("bn-callgraph.showIndirectCalls"):
		show_indirect = True

	visited = set()
	stack   = [current_function]
	while stack:
		func = stack.pop()

		calls = set()
		indirect_calls = set()
		external_calls = set()
		for llil_block in func.llil:
			for llil in llil_block:
				if llil.operation.name in {"LLIL_CALL", "LLIL_TAILCALL"}:
					if llil.dest.possible_values.type.name in {"ImportedAddressValue", "UndeterminedValue"}:
						if llil.dest.operation.name == "LLIL_LOAD" and llil.dest.src.possible_values.type.name == "ConstantPointerValue":
							# External function
							is_in_binary = False
							dst_addr = llil.dest.src.possible_values.value
							if dst_addr != 0:
								dst_fun_addr_raw = bv.read(dst_addr, bv.arch.address_size)
								if len(dst_fun_addr_raw) == bv.arch.address_size:
									# Its in the binary. Probably a shared library that exports a symbol that uses
									dst_fun_addr = int.from_bytes(
										dst_fun_addr_raw, "little" if bv.arch.endianness.name == "LittleEndian" else "big")
									dst_funs = bv.get_functions_at(dst_fun_addr)
									for dst_fun in dst_funs:
										calls.add(dst_fun)
										is_in_binary = True
							if not is_in_binary:
								# The function is not here
								symb = bv.get_symbol_at(dst_addr)
								if symb is not None:
									external_calls.add(ExternalFunction(symb.name))
						elif llil.dest.possible_values.type.name == "UndeterminedValue" and show_indirect:
							# Indirect call
							indirect_calls.add(UndeterminedFunction(llil.address))
					elif llil.dest.possible_values.type.name == "ConstantPointerValue":
						dst_funs = bv.get_functions_at(llil.dest.possible_values.value)
						for dst_fun in dst_funs:
							calls.add(dst_fun)

		for child_func in calls | indirect_calls | external_calls:
			graph.add(child_func, func)

			if child_func not in visited:
				if not isinstance(child_func, UndeterminedFunction) and not isinstance(child_func, ExternalFunction):
					stack.append(child_func)
		visited.add(func)
	graph.show()

def callgraph_reversed(bv, current_function):
	bv.update_analysis_and_wait()
	graph = GraphWrapper(current_function)

	visited = set()
	stack   = [current_function]
	while stack:
		func = stack.pop()
		for child_func in set(func.callers):
			graph.add(child_func, func)

			if child_func not in visited:
				stack.append(child_func)
		visited.add(func)
	graph.show()

class CallgraphThread(BackgroundTaskThread):
	def __init__(self, view, function, mode):
		super().__init__('Computing callgraph from {} [{}]...'.format(function.name, mode))
		self.view = view
		self.function = function
		self.mode = mode

	def run(self):
		if self.mode == "reversed":
			callgraph_reversed(self.view, self.function)
		else:
			callgraph(self.view, self.function)

def _wrapper(mode):
	def f(view, function):
		thread = CallgraphThread(view, function, mode)
		thread.start()
	return f

PluginCommand.register_for_function(
	"BNCallGraph\\Compute callgraph", 
	"", 
	_wrapper("normal")
)

PluginCommand.register_for_function(
	"BNCallGraph\\Compute reversed callgraph",
	"",
	_wrapper("reversed")
)
