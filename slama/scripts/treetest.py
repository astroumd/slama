from treelib import Tree
import json
class Air:
    def __init__(self,name):
        self.name = name
        self.heater = 0
        self.temperature = 0.0
        self.temperature_target = 0.0
        self.vent = 0.0

tree=Tree(identifier="SMA")
tree.create_node("Submillimeter Array","sma")
tree.create_node("Antennas","ant",parent='sma')
for i in range(1,9):
    tree.create_node(f'Ant{i}',f'ant{i}',parent='ant')
    #tree.create_node(f'Air With Data',f'airdata{i}',parent=f'ant{i}',
    #                 data = Air(f"air{i}"))
    tree.create_node(f'Air',f'air{i}',parent=f'ant{i}')
    tree.create_node(f'Heater',f'heater{i}',parent=f'air{i}')
    tree.create_node(f'Temperature',f'temperature{i}',parent=f'air{i}')
    tree.create_node(f'Temperature Target',f'temperature_target{i}',parent=f'air{i}')
    tree.create_node(f'Vent',f'vent{i}',parent=f'air{i}')


tree.show(line_type='ascii')
json_string = tree.to_json()
formatted_json = json.dumps(json.loads(tree.to_json()), indent=2)
#print(formatted_json)

#node = tree.get_node("airdata1")
#print(node.data.heater)
#print(tree.leaves())
print(tree.get_node('heater4').is_leaf())
print(tree.get_node('Ant1.Air'))
print(tree.get_node('ant1').successors('sma'))
print(tree.root)
print(tree.all_nodes())
ants = tree.leaves("ant")
print(type(ants[0]))
if True:
    for a in ants:
        print(f"{a.predecessor('SMA')} // {a.identifier}")
