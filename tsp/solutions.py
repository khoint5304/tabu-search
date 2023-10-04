from __future__ import annotations

import itertools
import re
from collections import deque
from os import path
from typing import ClassVar, Deque, Generic, Iterable, List, Optional, Set, Tuple, TypeVar, TYPE_CHECKING

from matplotlib import axes, pyplot

from .abc import BaseNeighborhood, BaseSolution
from .errors import ProblemNotFound, ProblemParsingException, UnsupportedEdgeWeightType


__all__ = (
    "PathSolution",
    "SwapNeighborhood",
)


class PathSolution(BaseSolution):

    __slots__ = (
        "__cost",
        "after",
        "before",
    )
    if TYPE_CHECKING:
        __cost: Optional[float]
        after: Tuple[int, ...]
        before: Tuple[int, ...]

        problem_name: ClassVar[str]
        dimension: ClassVar[int]
        edge_weight_type: ClassVar[str]
        distances: ClassVar[Tuple[Tuple[float, ...], ...]]

        x: Tuple[float, ...]
        y: Tuple[float, ...]

    def __init__(self, *, after: Iterable[int], before: Iterable[int], cost: Optional[float] = None) -> None:
        self.after = tuple(after)
        self.before = tuple(before)

        self.__cost = cost

    def cost(self) -> float:
        if self.__cost is not None:
            return self.__cost

        result = 0.0
        last, current = 0, self.after[0]
        while current != 0:
            result += self.distances[last][current]
            last, current = current, self.after[current]

        result += self.distances[last][current]
        self.__cost = result
        return result

    def get_neighborhoods(self) -> Iterable[BaseNeighborhood[PathSolution]]:
        return [
            SwapNeighborhood(self),
            SegmentShift(self, segment_length=1),
            SegmentShift(self, segment_length=2),
            SegmentShift(self, segment_length=3),
        ]

    def plot(self) -> None:
        _, ax = pyplot.subplots()
        assert isinstance(ax, axes.Axes)

        quiver_kwargs = {
            "color": "darkblue",
            "angles": "xy",
            "scale_units": "xy",
            "scale": 1,
        }
        for index in range(self.dimension):
            next = self.after[index]
            ax.quiver(self.x[index], self.y[index], self.x[next] - self.x[index], self.y[next] - self.y[index], **quiver_kwargs)

        ax.scatter(self.x, self.y, c="blue", label="City")
        for index in range(self.dimension):
            ax.annotate(index, (self.x[index], self.y[index]))

        ax.grid(True)

        pyplot.legend()
        pyplot.show()

    def get_path(self) -> Tuple[int]:
        path = [0]
        current = self.after[0]
        while current != 0:
            path.append(current)
            current = self.after[current]

        return tuple(path)

    @classmethod
    def initial(cls) -> PathSolution:
        after = [-1] * cls.dimension
        before = [-1] * cls.dimension

        path = [0]
        cities = set(range(1, cls.dimension))
        while len(cities) > 0:
            current = path[-1]
            insert = min(cities, key=cls.distances[current].__getitem__)
            path.append(insert)
            cities.remove(insert)

        for index in range(cls.dimension):
            after[path[index]] = path[(index + 1) % cls.dimension]
            before[path[index]] = path[(index - 1 + cls.dimension) % cls.dimension]

        return cls(after=after, before=before)

    @classmethod
    def import_problem(cls, problem: str, /) -> None:
        archive_file = path.join("problems", f"{problem}.tsp", f"{problem}.tsp")
        if not path.isfile(archive_file):
            raise ProblemNotFound(problem)

        cls.problem_name = problem
        try:
            with open(archive_file, "r") as file:
                data = file.read()

            cls.dimension = int(re.search(r"DIMENSION\s*:\s*(\d+)", data).group(1))
            cls.edge_weight_type = re.search(r"EDGE_WEIGHT_TYPE\s*:\s*(\w+)", data).group(1)

            if cls.edge_weight_type == "EUC_2D":
                distances = [[0.0] * cls.dimension for _ in range(cls.dimension)]
                x = []
                y = []
                for match in re.finditer(r"^\s*\d+\s+([\d\.\-+e]+\s+[\d\.\-+e]+)\s*?$", data, flags=re.MULTILINE):
                    _x, _y = map(float, match.group(1).split())
                    x.append(_x)
                    y.append(_y)

                cls.x = tuple(x)
                cls.y = tuple(y)

                for i in range(cls.dimension):
                    for j in range(i + 1, cls.dimension):
                        distances[i][j] = distances[j][i] = abs(x[i] - x[j]) + abs(y[i] - y[j])

                cls.distances = tuple(tuple(row) for row in distances)

                print(f"Found {cls.dimension} cities.")

            else:
                raise UnsupportedEdgeWeightType(cls.edge_weight_type)

        except Exception as exc:
            raise ProblemParsingException(problem, exc) from exc

    def __hash__(self) -> int:
        return hash(self.after)


TABU_T = TypeVar("TABU_T")


class _BasePathNeighborhood(BaseNeighborhood[PathSolution], Generic[TABU_T]):

    __slots__ = ()
    if TYPE_CHECKING:
        _maxlen: ClassVar[int]
        _tabu_list: ClassVar[Deque[TABU_T]]
        _tabu_set: ClassVar[Set[TABU_T]]

    @classmethod
    def add_to_tabu(cls, target: TABU_T) -> None:
        cls._tabu_set.add(target)
        cls._tabu_list.append(target)
        cls.remove_from_tabu()

    @classmethod
    def remove_from_tabu(cls) -> None:
        while len(cls._tabu_set) > cls._maxlen:
            try:
                cls._tabu_set.remove(cls._tabu_list.popleft())
            except KeyError:
                pass

    @classmethod
    def reset_tabu(cls, *, maxlen: int = 100) -> None:
        cls._maxlen = maxlen
        cls.remove_from_tabu()


class SwapNeighborhood(_BasePathNeighborhood[Tuple[int, int]]):

    __slots__ = ()
    _maxlen: ClassVar[int] = 100
    _tabu_list: ClassVar[Deque[Tuple[int, int]]] = deque()
    _tabu_set: ClassVar[Set[Tuple[int, int]]] = set()

    def swap(self, x: int, y: int) -> PathSolution:
        solution = self._solution

        before = list(solution.before)
        after = list(solution.after)

        before_x = before[x]
        before_y = before[y]
        after_x = after[x]
        after_y = after[y]

        cost = (
            solution.cost()
            + solution.distances[before_x][y] + solution.distances[y][after_x]
            + solution.distances[before_y][x] + solution.distances[x][after_y]
            - solution.distances[before_x][x] - solution.distances[x][after_x]
            - solution.distances[before_y][y] - solution.distances[y][after_y]
        )

        before[x], before[y] = before_y, before_x
        after[x], after[y] = after_y, after_x

        after[before_x] = before[after_x] = y
        after[before_y] = before[after_y] = x

        return PathSolution(after=after, before=before, cost=cost)

    def find_best_candidate(self) -> Optional[PathSolution]:
        result: Optional[PathSolution] = None
        min_pair: Optional[Tuple[int, int]] = None
        for first, second in itertools.combinations(range(self._solution.dimension), 2):
            # first < second due to itertools.combinations implementation

            after = self._solution.after.__getitem__
            if after(first) == second or after(second) == first or after(after(first)) == second or after(after(second)) == first:
                continue

            pair = (first, second)
            if pair not in self._tabu_set:
                swapped = self.swap(first, second)
                if result is None or swapped < result:
                    result = swapped
                    min_pair = pair

        if min_pair is not None:
            self.add_to_tabu(min_pair)

        return result


class SegmentShift(_BasePathNeighborhood[Tuple[int, int]]):

    __slots__ = (
        "__segment_length",
    )
    _maxlen: ClassVar[int] = 100
    _tabu_list: ClassVar[Deque[Tuple[int, int]]] = deque()
    _tabu_set: ClassVar[Set[Tuple[int, int]]] = set()
    if TYPE_CHECKING:
        __segment_length: int

    def __init__(self, solution: PathSolution, *, segment_length: int) -> None:
        super().__init__(solution)
        self.__segment_length = segment_length

    def insert_after(self, segment: List[int], x: int) -> PathSolution:
        solution = self._solution

        before = list(solution.before)
        after = list(solution.after)

        before_segment = before[segment[0]]
        after_segment = after[segment[-1]]
        after_x = after[x]

        cost = (
            solution.cost()
            + solution.distances[before_segment][after_segment]
            + solution.distances[x][segment[0]] + solution.distances[segment[-1]][after_x]
            - solution.distances[before_segment][segment[0]] - solution.distances[segment[-1]][after_segment]
            - solution.distances[x][after_x]
        )

        after[before_segment], before[after_segment] = after_segment, before_segment
        after[x], before[segment[0]] = segment[0], x
        after[segment[-1]], before[after_x] = after_x, segment[-1]

        return PathSolution(after=after, before=before, cost=cost)

    def find_best_candidate(self) -> Optional[PathSolution]:
        solution = self._solution
        if solution.dimension + 2 < self.__segment_length:
            return None

        result: Optional[PathSolution] = None
        min_pair: Optional[Tuple[int, int]] = None

        path = self._solution.get_path()
        for index in range(solution.dimension):
            segment: List[int] = []
            for d in range(self.__segment_length):
                segment.append(path[(index + d) % solution.dimension])

            for index in range(solution.dimension):
                if index != solution.before[segment[0]] and index != solution.after[segment[-1]] and index not in segment:  # For small length segments only, ~O(1) for checking existence
                    pair = (segment[0], index)
                    if pair not in self._tabu_set:
                        inserted = self.insert_after(segment, index)
                        if result is None or inserted < result:
                            result = inserted
                            min_pair = pair

        if min_pair is not None:
            self.add_to_tabu(min_pair)

        return result
