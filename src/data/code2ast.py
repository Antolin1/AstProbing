#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Jan 29 16:08:24 2022

@author: Jose Antonio
"""

from .utils import remove_comments_and_docstrings_python, remove_comments_and_docstrings_java_js
import networkx as nx
from scipy.stats import spearmanr

#aux function, get a new id in the graph
def getId(G):
    if len(G) == 0:
        return 0
    return max(list(G)) + 1

#aux function used to get the graph associated to the ast
def getGraphFromTree(node, G, id_father):
    #traverse children
    for child in node.children:
        is_terminal_child = (len(child.children) == 0)
        id_child = getId(G)
        G.add_node(id_child, type = child.type,
                      is_terminal = is_terminal_child,
                      start = child.start_byte,
                      end = child.end_byte)
        G.add_edge(id_father,id_child)
        getGraphFromTree(child, G, id_child)

#get token given the code, the start byte and the end byte
def getToken(code, start, end):
    return bytes(code, "utf8")[start:end].decode("utf-8") 


#get the possible candiate as head given a nonterminal level
def getCandidate(G, level, start):
    #reachable nodes
    nodes = list(nx.single_source_shortest_path_length(G, level).keys())
    #filter non-terminals
    nodes = [n for n in nodes if G.nodes[n]['is_terminal']]
    #filter right ones
    nodes = [n for n in nodes if G.nodes[n]['start'] < start]
    if len(nodes) == 0:
        return None
    #sort by start
    nodes.sort(key=lambda n: G.nodes[n]['start'])
    return nodes[0]

#get the head of a given non-terminal that is not the root
def selectHead(G, n):
    father = list(G.in_edges(n))[0][0]
    while(True):
        cand = getCandidate(G, father, G.nodes[n]['start'])
        if cand != None:
            return cand
        father = list(G.in_edges(father))[0][0]

#get root dependency tree
def getRoot(G):
    nodes = list(G.nodes)
    nodes = [n for n in nodes if G.nodes[n]['is_terminal']]
    nodes.sort(key=lambda n: G.nodes[n]['start'])
    return nodes[0]

#get the tokens of the dependency tree
def getTokens(T, code):
    return [getToken(code, T.nodes[t]['start'], T.nodes[t]['end']) for t in sorted(list(T.nodes), 
                                                 key = lambda n: T.nodes[n]['start'])]


#preprocess code, obtain the ast and returns a network graph.
#it returns the graph of the ast and the preprocessed code
#directed graph
def code2ast(code, parser, lang='python'):
    if lang == 'python':
        #preprocess
        code = remove_comments_and_docstrings_python(code)
        tree = parser.parse(bytes(code, "utf8"))
        
        G = nx.DiGraph()
        #add root
        G.add_node(0, type = tree.root_node.type,
                      is_terminal = False,
                      start = tree.root_node.start_byte,
                      end = tree.root_node.end_byte)
        getGraphFromTree(tree.root_node, G, 0)
        return G, code
    elif lang == 'javascript':
        code = remove_comments_and_docstrings_java_js(code)
        tree = parser.parse(bytes(code, "utf8"))

        G = nx.DiGraph()
        # add root
        G.add_node(0, type=tree.root_node.type,
                   is_terminal=False,
                   start=tree.root_node.start_byte,
                   end=tree.root_node.end_byte)
        getGraphFromTree(tree.root_node, G, 0)
        return G, code

#it adds dependency labels between non-terminals to the previous obtained ast graph
#directed graph
def enrichAstWithDeps(G):
    root = getRoot(G)
    nodes = [n for n in list(G.nodes) if root!=n and G.nodes[n]['is_terminal']]
    for n in nodes:
        h = selectHead(G, n)
        G.add_edge(h, n, label = 'dependency')
        
#obtains the dependecency subgraph from the enriched one,
#returns directed graph
def getDependencyTree(G):
    view = nx.subgraph_view(G, filter_node=lambda n: G.nodes[n]['is_terminal'],
                            filter_edge=lambda n1, n2: G[n1][n2].get("label", 'dependency'))
    return nx.DiGraph(view)

#obtains the distance matrix from the dependency graph
def getMatrixAndTokens(T, code):
    distance = nx.floyd_warshall_numpy(nx.Graph(T), sorted(list(T.nodes), 
                                                 key = lambda n: T.nodes[n]['start']))
    tokens = getTokens(T, code)
    return distance, tokens

#G directed ast without dependency labels
#T directed dependency tree
#both must be aligned
#add label to edges in T with the nonterminals
#when recover ast, left of [] and [] dont create. right create
def labelDepTree(G, T):
    root = getRoot(G)
    nodes = [n for n in list(G.nodes) if root != n and G.nodes[n]['is_terminal']]
    types = nx.get_node_attributes(G, 'type')
    for n in nodes:
        h = getHeadDepTree(T, n)
        if h == root:
            nodes = nx.shortest_path(nx.Graph(G), source=h, target=n)[1:-1]
            node_types = [types[m] for m in nodes]
            node_depths = [getDepth(G, m, root) for m in nodes]
            special_index = 0
            edge_data = ComplexEdgeLabels(node_types, node_depths, special_index)
            #node_types[0] = ('[' + node_types[0][0] + ']', node_types[0][1])
            #node_types = '|'.join(node_types)
            T[h][n]['complex_edge'] = edge_data
            T[h][n]['complex_edge_str'] = str(edge_data)
        else:
            h_head = getHeadDepTree(T, h)
            spine_head = nx.shortest_path(nx.Graph(G), source=h, target=h_head)[1:-1]
            spine_n = nx.shortest_path(nx.Graph(G), source=h, target=n)[1:-1]
            index = None
            for j,m in enumerate(spine_n):
                if m in spine_head:
                    index = spine_head.index(m)
            if index == None:
                index = len(spine_n) - 1
            spine_n_types = [types[m] for m in spine_n]
            node_depths = [getDepth(G, m, root) for m in spine_n]
            edge_data = ComplexEdgeLabels(spine_n_types, node_depths, index)
            T[h][n]['complex_edge'] = edge_data
            T[h][n]['complex_edge_str'] = str(edge_data)
            #spine_n[index] = '[' + spine_n[index] + ']'
            #spine_n = '|'.join(spine_n)
            #T[h][n]['seq_nonterminal'] = spine_n

#given the labeled directed dep tree, it generates the tuples (s,t,label)
def get_tuples_from_labeled_dep_tree(T, code):
    pairs = []
    sorted_nodes = sorted(list(T.nodes),
           key=lambda n: T.nodes[n]['start'])
    for s, t, label in ((*edge, d['complex_edge_str']) for *edge, d in T.edges(data=True)):
        pairs.append((sorted_nodes.index(s), sorted_nodes.index(t), label))
    tokens = getTokens(T, code)
    return pairs, tokens

#aux function
def getHeadDepTree(T,n):
    return list(T.in_edges(n))[0][0]
    dataset_name_or_path: Optional[str] = field(
        default=None,
        metadata={'help': 'Local path to the dataset or its name on Huggingface datasets hub.'}
    )
#aux function
def getDepth(G, n, root):
    return len(nx.shortest_path(nx.Graph(G), source=n, target=root)[1:-1])

#aux class
class ComplexEdgeLabels:
    def __init__(self, non_terminals, depths, special_index):
        self.non_terminals = non_terminals
        self.depths = depths
        self.special_index = special_index
    def __str__(self):
        return str(self.special_index) + '-' + '|'.join(self.non_terminals[self.special_index+1:])


    def get_node_to_append(self, path):
        #print('Non-terminals',self.non_terminals)
        #print('Index', self.special_index)
        node_append = path[self.special_index]
        to_append = self.non_terminals[self.special_index+1:]
        return node_append, to_append

#function used to test if it is possible to obtain the ast from the labeled dep tree
def from_label_dep_tree_to_ast(T, lang='python'):
    T_ast = nx.Graph()
    root = getRoot(T)
    types = nx.get_node_attributes(T, 'type')
    if lang == 'python':
        T_ast.add_node(0, type='module', is_terminal=False)
        T_ast.add_node(1, type='function_definition', is_terminal=False)
        T_ast.add_node(2, **T.nodes[root])
        T_ast.add_edge(0, 1)
        T_ast.add_edge(1, 2)
        nodes = [n for n in T.nodes if n!=root]
        nodes.sort(key=lambda n: T.nodes[n]['start'])
        for n in nodes:
            h = getHeadDepTree(T, n)
            if h == root:
                path = nx.shortest_path(T_ast, source=2, target=0)[1:-1]
            else:
                h_head = getHeadDepTree(T, h)
                h_correspondence = get_correspondence(T_ast, T, h)
                h_head_correspondence = get_correspondence(T_ast, T, h_head)
                path = nx.shortest_path(T_ast, source=h_correspondence,
                                        target=h_head_correspondence)[1:-1]
            edge_data = T[h][n]['complex_edge']
            node_append, to_append = edge_data.get_node_to_append(path)
            #print('To append',to_append)
            #print('To append terminal', T.nodes[n])
            #print('-'*100)
            #add non terminals
            for nt in to_append:
                m = getId(T_ast)
                T_ast.add_node(m, type=nt, is_terminal=False)
                T_ast.add_edge(m, node_append)
                node_append = m
            #add terminal
            m = getId(T_ast)
            T_ast.add_node(m, **T.nodes[n])
            T_ast.add_edge(m, node_append)
    return T_ast

#aux funtion
def get_correspondence(T_ast, T, n):
    for m in T_ast:
        if T_ast.nodes[m] == T.nodes[n]:
            return m

#build tree from distance matrix,
#undirected graph, run this also for the ground truth
# TODO, remove tokens
def getTreeFromDistances(distances, tokens):
    G = nx.Graph()
    for j,t in enumerate(tokens):
        G.add_node(j, type=t)
    for i,_ in enumerate(tokens):
        for j,_ in enumerate(tokens):
            G.add_edge(i,j, weight=distances[i][j])
    T = nx.minimum_spanning_tree(G)
    return T

#compare two (undirected) trees, they have to be aligned
def getUAS(T_true, T_pred):
    assert len(T_true) == len(T_pred)
    assert len(T_true.edges) == len(T_pred.edges)
    count = 0
    i = 0
    for s,t in T_pred.edges:
        if T_true.has_edge(s,t):
            count += 1
        i += 1
    return float(count)/float(i)

#spearman coef, it receives two distance matrices that are aligned
def getSpear(d_true, d_pred):
    spearmanrs = [spearmanr(pred, gold) for pred, gold in zip(d_true, d_pred)]
    return [x.correlation for x in spearmanrs]
    