# Copyright 2020 University of Groningen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import random
import networkx as nx
import numpy as np
from numpy.linalg import norm
from .processor import Processor
from .linalg_functions import norm_sphere

"""
Processor implementing a random-walk to generate
coordinates for a meta-molecule.
"""

def _take_step(vectors, step_length, coord):
    """
    Given a list of unit `vectors` choose one randomly,
    multiply it by the `step_length` and add to `coord`.

    Parameters
    ----------
    vectors: list[np.ndarray(n, 3)]
    step_length: float
    coord: np.ndarray(3)

    Returns
    -------
    np.ndarray(3)
        the new coordinate
    int
        the index of the vector choosen
    """
    index = random.randint(0, len(vectors) - 1)
    new_coord = coord + vectors[index] * step_length
    return new_coord, index

def not_exceeds_max_dimensions(point, maxdim):
    return np.all(point < maxdim) and np.all(point > np.array([0., 0., 0.]))

def is_pushed(point, old_point, push):
    allowed = {"x": [0, 1],
               "y": [1, 1],
               "z": [2, 1],
               "nx": [0, -1],
               "ny": [1, -1],
               "nz": [2, -1]}
    if any([vect not in allowed for vect in push]):
       raise IOError

    if len(push) >= 6:
        raise IOError

    for direction in push:
        pos, sign = allowed[direction]
        if direction in ["x", "y", "z"] and point[pos] < old_point[pos]:
            return False
        elif  direction in ["nx", "ny", "nz"] and point[pos] > old_point[pos]:
            return False
    else:
        return True

def _find_starting_node(meta_molecule):
    """
    Find the first node that has coordinates if there is
    otherwise return first node in list of nodes.
    """
    for node, build in nx.get_node_attributes(meta_molecule, "build").items():
        if not build:
           return node
    else:
        return list(meta_molecule.nodes())[0]


class RandomWalk(Processor):
    """
    Add coordinates at the meta_molecule level
    through a random walk for all nodes which have
    build defined as true.
    """

    def __init__(self,
                 mol_idx,
                 nonbond_matrix,
                 start=np.array([0, 0, 0]),
                 step_fudge=0.8,
                 maxiter=80,
                 maxdim=None,
                 max_force=10**3.0,
                 vector_sphere=norm_sphere(5000),
                 push=[]):

        self.mol_idx = mol_idx
        self.nonbond_matrix = nonbond_matrix
        self.start = start
        self.maxiter = maxiter
        self.maxdim = maxdim
        self.vector_sphere = vector_sphere
        self.success = False
        self.max_force = max_force
        self.push = push
        self.step_fudge = step_fudge

    def _rewind(self, current_step, placed_nodes, nsteps):
        for node in placed_nodes[-nsteps:]:
             dummy_point = np.array([np.inf, np.inf, np.inf])
             self.nonbond_matrix.update_positions(dummy_point,
                                                  self.mol_idx,
                                                  node)

    def _is_overlap(self, point, node, nrexcl=1):
        neighbours = nx.neighbors(self.molecule, node)
        force_vect = self.nonbond_matrix.compute_force_point(point,
                                                             self.mol_idx,
                                                             node,
                                                             neighbours,
                                                             potential="LJ")
        return norm(force_vect) > self.max_force

    def update_positions(self, vector_bundle, current_node, prev_node):
        """
        Take an array of unit vectors `vector_bundle` and generate the coordinates
        for `current_node` by adding a random vector to the position of the previous
        node `prev_node`. The length of that vector is defined as 2 times the vdw-radius
        of the two nodes. The position is updated in place.

        Parameters
        ----------
        vector_bunde: np.ndarray(m,3)
        meta_molecule: :class:polyply.src.meta_molecule.MetaMolecule
        current_node: node_key[int, str]
        prev_node: node_key[int, str]
        topology: :class:polyply.src.topology.Topology
        maxiter: int
           maximum number of iterations
        """

        last_point = self.nonbond_matrix.get_point(self.mol_idx, prev_node)
        step_length = self.step_fudge * self.nonbond_matrix.get_interaction(self.mol_idx,
                                                                self.mol_idx,
                                                                prev_node,
                                                                current_node)[0]
        step_count = 0
        while True:
            new_point, index = _take_step(vector_bundle, step_length, last_point)
            overlap = self._is_overlap(new_point, current_node)
            in_box = not_exceeds_max_dimensions(new_point, self.maxdim)
            pushed = is_pushed(new_point, last_point, self.push)
 
            if not overlap and in_box and pushed:
                self.nonbond_matrix.update_positions(new_point, self.mol_idx, current_node)
                return True
            elif step_count == self.maxiter:
                return False
            else:
                step_count += 1
                vector_bundle = np.delete(vector_bundle, index, axis=0)

    def _random_walk(self, meta_molecule):
        """
        Perform a random_walk to build positions for a meta_molecule, if
        no position is present for an atom.

        Parameters
        ----------
        meta_molecule:  :class:`polyply.src.meta_molecule.MetaMolecule`
        """
        first_node = _find_starting_node(meta_molecule)
        if "position" not in meta_molecule.nodes[first_node]:
            if not self._is_overlap(self.start, first_node):
                self.nonbond_matrix.update_positions(self.start, self.mol_idx, first_node)
                self.success = True
            else:
                self.success = False
                return

        vector_bundle = self.vector_sphere.copy()
        count = 0
        placed_nodes = []
        path = list(nx.bfs_edges(meta_molecule, source=first_node))
        step_count = 0
        while step_count < len(path):
            print(step_count)
            prev_node, current_node = path[step_count]
            #print(meta_molecule.nodes[current_node]["resname"])
            if "position" in meta_molecule.nodes[current_node]:
                step_count += 1
                continue

            status = self.update_positions(vector_bundle,
                                           current_node,
                                           prev_node)
            self.success = status
            placed_nodes.append(current_node)

            if not self.success and count < self.maxiter:
                if step_count < 5:
                   return
                else:
                   nrewind = 5
                self._rewind(step_count, placed_nodes, nrewind)
                step_count = step_count - nrewind
            elif not self.success:
                return
            else:
                count = 0
                step_count += 1

            count += 1

    def run_molecule(self, meta_molecule):
        """
        Perform the random walk for a single molecule.
        """
        self.molecule = meta_molecule
        self._random_walk(meta_molecule)
        return meta_molecule
