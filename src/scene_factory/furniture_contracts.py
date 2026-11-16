"""Pure assembly contracts; measured boxes may replace planned component bounds."""
from .spec import SpecError

EPS=2e-5

def require(test,message):
    if not test:raise SpecError('furniture: '+message)

def transformed_box(matrix,low,high):
    import itertools
    points=[[sum(matrix[i][j]*v[j] for j in range(3))+matrix[i][3] for i in range(3)] for v in itertools.product(*zip(low,high))]
    return [[min(v[i] for v in points) for i in range(3)],[max(v[i] for v in points) for i in range(3)]]

def box(node):
    p=node['parameters'];return transformed_box(node['world_matrix'],[-p['width']/2,-p['depth']/2,0],[p['width']/2,p['depth']/2,p['height']])

def overlap(a,b):return all(min(a[1][i],b[1][i])-max(a[0][i],b[0][i])>EPS for i in range(3))
def contact(a,b):return all(min(a[1][i],b[1][i])-max(a[0][i],b[0][i])>=-EPS for i in range(3))

def check_part(node,nodes):
    p=node['parameters'];require(p['bevel']*2<min(p['width'],p['depth'],p['height']),'bevel exceeds component thickness')

def assembly(node,nodes,measured=None,connected=True):
    parts=[n for n in nodes.values() if n['skill']['skill_id']=='furniture_part' and node['node_id'] in n['lineage']]
    require(bool(parts),'assembly has no components')
    boxes={n['node_id']:(measured[n['node_id']] if measured is not None else box(n)) for n in parts};edges={k:set() for k in boxes}
    keys=list(boxes)
    for i,key in enumerate(keys):
        for other in keys[:i]:
            require(not overlap(boxes[key],boxes[other]),f'components intersect: {key}/{other}')
            if contact(boxes[key],boxes[other]):edges[key].add(other);edges[other].add(key)
    if connected:
        seen={keys[0]};todo=[keys[0]]
        while todo:
            for nxt in edges[todo.pop()]-seen:seen.add(nxt);todo.append(nxt)
        require(len(seen)==len(boxes),'detached component / invalid attachment graph')
    return edges

def check_assembly(node,nodes):assembly(node,nodes)
def check_group(node,nodes):assembly(node,nodes,connected=False)
