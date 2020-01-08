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

		self.graph.show("Callgraph starting from {}".format(self.root_function.name))

def callgraph(bv, current_function):
	bv.update_analysis_and_wait()
	graph = GraphWrapper(current_function)

	visited = set()
	stack   = [current_function]
	while stack:
		func = stack.pop()
		for child_func in set(func.callees):
			graph.add(child_func, func)

			if child_func not in visited:
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
