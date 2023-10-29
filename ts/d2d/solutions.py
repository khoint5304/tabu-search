from __future__ import annotations

import itertools
import re
from functools import partial
from math import sqrt
from os.path import join
from typing import Any, ClassVar, Iterable, List, Optional, Sequence, Tuple, TYPE_CHECKING, final

from matplotlib import axes, pyplot
if TYPE_CHECKING:
    from typing_extensions import Self

from .config import DroneEnduranceConfig, DroneEnergyConsumptionMode, DroneLinearConfig, DroneNonlinearConfig, TruckConfig
from .errors import ImportException
from .mixins import SolutionMetricsMixin
from .neighborhoods import Swap
from ..abc import MultiObjectiveNeighborhood, MultiObjectiveSolution


__all__ = ("D2DPathSolution",)


@final
class D2DPathSolution(SolutionMetricsMixin, MultiObjectiveSolution):
    """Represents a solution to the D2D problem"""

    __slots__ = (
        "_to_propagate",
        "drone_arrival_timestamps",
        "drone_paths",
        "technician_arrival_timestamps",
        "technician_paths",
    )
    __config_imported: ClassVar[bool] = False
    problem: ClassVar[Optional[str]] = None
    if TYPE_CHECKING:
        _to_propagate: bool
        drone_arrival_timestamps: Tuple[Tuple[Tuple[float, ...], ...], ...]
        drone_paths: Tuple[Tuple[Tuple[int, ...], ...], ...]
        technician_arrival_timestamps: Tuple[Tuple[float, ...], ...]
        technician_paths: Tuple[Tuple[int, ...], ...]

        # Problem-specific data
        customers_count: ClassVar[int]
        drones_count: ClassVar[int]
        technicians_count: ClassVar[int]
        drones_flight_duration: ClassVar[float]

        x: ClassVar[Tuple[float, ...]]
        y: ClassVar[Tuple[float, ...]]
        demands: ClassVar[Tuple[float, ...]]
        dronable: ClassVar[Tuple[bool, ...]]
        drone_service_time: ClassVar[Tuple[float, ...]]
        technician_service_time: ClassVar[Tuple[float, ...]]

        # Global configuration data
        energy_mode: ClassVar[DroneEnergyConsumptionMode]
        truck_config: ClassVar[TruckConfig]
        drone_linear_config: ClassVar[Tuple[DroneLinearConfig, ...]]
        drone_nonlinear_config: ClassVar[Tuple[DroneNonlinearConfig, ...]]
        drone_endurance_config: ClassVar[Tuple[DroneEnduranceConfig, ...]]

    def __init__(
        self,
        *,
        drone_paths: Iterable[Iterable[Iterable[int]]],
        technician_paths: Iterable[Iterable[int]],
        drone_arrival_timestamps: Optional[Tuple[Tuple[Tuple[float, ...], ...], ...]] = None,
        technician_arrival_timestamps: Optional[Tuple[Tuple[float, ...], ...]] = None,
        drone_timespans: Optional[Tuple[float, ...]] = None,
        drone_waiting_times: Optional[Tuple[Tuple[float, ...], ...]] = None,
        technician_timespans: Optional[Tuple[float, ...]] = None,
        technician_waiting_times: Optional[Tuple[float, ...]] = None,
    ) -> None:
        self._to_propagate = True
        self.drone_paths = tuple(tuple(tuple(index for index in path) for path in paths) for paths in drone_paths)
        self.technician_paths = tuple(tuple(index for index in path) for path in technician_paths)

        if drone_arrival_timestamps is None:
            def get_arrival_timestamps() -> Tuple[Tuple[Tuple[float, ...], ...], ...]:
                result: List[List[Tuple[float, ...]]] = []
                for drone, paths in enumerate(self.drone_paths):
                    drone_arrivals: List[Tuple[float, ...]] = []
                    result.append(drone_arrivals)

                    offset = 0.0
                    for path in paths:
                        arrivals = self.calculate_drone_arrival_timestamps(path, drone=drone, offset=offset)
                        offset = arrivals[-1]
                        drone_arrivals.append(arrivals)

                return tuple(tuple(paths) for paths in result)

            drone_arrival_timestamps = get_arrival_timestamps()

        self.drone_arrival_timestamps = drone_arrival_timestamps

        if technician_arrival_timestamps is None:
            technician_arrival_timestamps = tuple(self.calculate_technician_arrival_timestamps(path) for path in self.technician_paths)

        self.technician_arrival_timestamps = technician_arrival_timestamps

        def __last_element(__tuple: Tuple[Tuple[float, ...], ...]) -> float:
            try:
                return __tuple[-1][-1]
            except IndexError:
                return 0.0

        super().__init__(
            drone_timespans=drone_timespans or tuple(__last_element(single_drone_arrival_timestamps) for single_drone_arrival_timestamps in self.drone_arrival_timestamps),
            drone_waiting_times=drone_waiting_times or tuple(
                tuple(
                    self.calculate_drone_total_waiting_time(path, drone=drone, arrival_timestamps=arrival_timestamps)
                    for path, arrival_timestamps in zip(paths, self.drone_arrival_timestamps[drone])
                )
                for drone, paths in enumerate(self.drone_paths)
            ),
            technician_timespans=technician_timespans or tuple(technician_arrival_timestamp[-1] for technician_arrival_timestamp in self.technician_arrival_timestamps),
            technician_waiting_times=technician_waiting_times or tuple(self.calculate_technician_total_waiting_time(path, arrival_timestamps=arrival_timestamps) for path, arrival_timestamps in zip(self.technician_paths, self.technician_arrival_timestamps)),
        )

    @property
    def to_propagate(self) -> bool:
        return self._to_propagate

    @to_propagate.setter
    def to_propagate(self, propagate: bool) -> None:
        self._to_propagate = propagate

    def get_neighborhoods(self) -> Tuple[MultiObjectiveNeighborhood[Self, Any], ...]:
        return (
            Swap(self, first_length=1, second_length=1),
            Swap(self, first_length=2, second_length=1),
            Swap(self, first_length=2, second_length=2),
        )

    def plot(self) -> None:
        _, ax = pyplot.subplots()
        assert isinstance(ax, axes.Axes)

        for paths in self.drone_paths:
            drone_x: List[float] = []
            drone_y: List[float] = []
            drone_u: List[float] = []
            drone_v: List[float] = []
            for path in paths:
                for index in range(len(path) - 1):
                    current = path[index]
                    after = path[index + 1]

                    drone_x.append(self.x[current])
                    drone_y.append(self.y[current])
                    drone_u.append(self.x[after] - self.x[current])
                    drone_v.append(self.y[after] - self.y[current])

            ax.quiver(
                drone_x,
                drone_y,
                drone_u,
                drone_v,
                color="cyan",
                angles="xy",
                scale_units="xy",
                scale=1,
            )

        for path in self.technician_paths:
            technician_x: List[float] = []
            technician_y: List[float] = []
            technician_u: List[float] = []
            technician_v: List[float] = []
            for index in range(len(path) - 1):
                current = path[index]
                after = path[index + 1]

                technician_x.append(self.x[current])
                technician_y.append(self.y[current])
                technician_u.append(self.x[after] - self.x[current])
                technician_v.append(self.y[after] - self.y[current])

            ax.quiver(
                technician_x,
                technician_y,
                technician_u,
                technician_v,
                color="darkviolet",
                angles="xy",
                scale_units="xy",
                scale=1,
            )

        ax.scatter((0,), (0,), c="black", label="Deport")
        ax.scatter(
            [self.x[index] for index in range(1, 1 + self.customers_count) if self.dronable[index]],
            [self.y[index] for index in range(1, 1 + self.customers_count) if self.dronable[index]],
            c="darkblue",
            label="Dronable",
        )
        ax.scatter(
            [self.x[index] for index in range(1, 1 + self.customers_count) if not self.dronable[index]],
            [self.y[index] for index in range(1, 1 + self.customers_count) if not self.dronable[index]],
            c="red",
            label="Technician-only",
        )

        ax.annotate("0", (0, 0))
        for index in range(1, 1 + self.customers_count):
            ax.annotate(str(index), (self.x[index], self.y[index]))

        ax.grid(True)

        pyplot.legend()
        pyplot.show()

    @classmethod
    def distance(cls, first: int, second: int, /) -> float:
        return sqrt((cls.x[first] - cls.x[second]) ** 2 + (cls.y[first] - cls.y[second]) ** 2)

    @classmethod
    def calculate_drone_arrival_timestamps(cls, path: Sequence[int], *, drone: int, offset: float) -> Tuple[float, ...]:
        result = [offset]
        last = path[0]  # must be 0
        config = cls.drone_linear_config[drone] if cls.energy_mode == DroneEnergyConsumptionMode.LINEAR else cls.drone_nonlinear_config[drone]
        vertical_time = config.altitude * (1 / config.takeoff_speed + 1 / config.landing_speed)

        for index in path[1:]:
            result.append(result[-1] + cls.drone_service_time[last] + vertical_time + cls.distance(last, index) / config.cruise_speed)
            last = index

        return tuple(result)

    @classmethod
    def _ensure_drone_arrival_timestamps(
        cls,
        path: Sequence[int],
        *,
        drone: Optional[int] = None,
        arrival_timestamps: Optional[Tuple[float, ...]] = None,
    ) -> Tuple[float, ...]:
        if arrival_timestamps is None:
            if drone is None:
                message = "Unknown drone for waiting time calculation"
                raise ValueError(message)

            arrival_timestamps = cls.calculate_drone_arrival_timestamps(path, drone=drone, offset=0.0)

        return arrival_timestamps

    @classmethod
    def calculate_drone_total_waiting_time(
        cls,
        path: Sequence[int],
        *,
        drone: Optional[int] = None,
        arrival_timestamps: Optional[Tuple[float, ...]] = None,
    ) -> float:
        arrival_timestamps = cls._ensure_drone_arrival_timestamps(path, drone=drone)

        result = 0.0
        for path_index, index in enumerate(path):
            result += arrival_timestamps[-1] - arrival_timestamps[path_index] - cls.drone_service_time[index]

        return result

    @classmethod
    def calculate_technician_arrival_timestamps(cls, path: Sequence[int]) -> Tuple[float, ...]:
        result = [0.0]
        last = path[0]  # must be 0
        config = cls.truck_config

        coefficients_iter = itertools.cycle(config.coefficients)
        current_within_timespan = 0.0
        velocity = config.maximum_velocity * next(coefficients_iter)

        for index in path[1:]:
            timestamp = result[-1]
            distance = cls.distance(last, index)

            while distance > 0:
                time_shift = min(distance / velocity, 3600.0 - current_within_timespan)
                timestamp += time_shift
                distance -= time_shift * velocity
                current_within_timespan += time_shift

                if current_within_timespan >= 3600.0:
                    current_within_timespan = 0.0
                    velocity = config.maximum_velocity * next(coefficients_iter)

            result.append(timestamp)
            last = index

        return tuple(result)

    @classmethod
    def calculate_technician_total_waiting_time(cls, path: Sequence[int], *, arrival_timestamps: Optional[Tuple[float, ...]] = None) -> float:
        if arrival_timestamps is None:
            arrival_timestamps = cls.calculate_technician_arrival_timestamps(path)

        result = 0.0
        for path_index, index in enumerate(path):
            result += arrival_timestamps[-1] - arrival_timestamps[path_index] - cls.technician_service_time[index]

        return result

    @classmethod
    def calculate_total_weight(cls, path: Sequence[int]) -> float:
        return sum(cls.demands[index] for index in path)

    @classmethod
    def calculate_drone_flight_duration(
        cls,
        path: Sequence[int],
        *,
        drone: Optional[int] = None,
        arrival_timestamps: Optional[Tuple[float, ...]] = None,
    ) -> float:
        arrival_timestamps = cls._ensure_drone_arrival_timestamps(path, drone=drone, arrival_timestamps=arrival_timestamps)
        return arrival_timestamps[-1] - arrival_timestamps[0]

    @classmethod
    def calculate_drone_energy_consumption(
        cls,
        path: Sequence[int],
        *,
        drone: int,
        arrival_timestamps: Optional[Tuple[float, ...]] = None,
    ) -> float:
        arrival_timestamps = cls._ensure_drone_arrival_timestamps(path, drone=drone, arrival_timestamps=arrival_timestamps)
        config = cls.drone_linear_config[drone] if cls.energy_mode == DroneEnergyConsumptionMode.LINEAR else cls.drone_nonlinear_config[drone]

        takeoff_time = config.altitude / config.takeoff_speed
        landing_time = config.altitude / config.landing_speed

        result = weight = 0.0
        for path_index, index in enumerate(path[1:], start=1):
            last = path[path_index - 1]
            cruise_time = cls.distance(last, index) / config.cruise_speed
            result += (
                takeoff_time * config.takeoff_power(weight)
                + cruise_time * config.cruise_power(weight)
                + landing_time * config.landing_power(weight)
            )

            weight += cls.demands[index]

        return result

    @classmethod
    def initial(cls) -> D2DPathSolution:
        # Serve all technician-only waypoints
        technician_paths = [[0] for _ in range(cls.technicians_count)]
        technician_only = set(e for e in range(1, 1 + cls.customers_count) if not cls.dronable[e])

        technician_paths_iter = itertools.cycle(technician_paths)
        while len(technician_only) > 0:
            path = next(technician_paths_iter)
            index = min(technician_only, key=partial(cls.distance, path[-1]))
            path.append(index)
            technician_only.remove(index)

        for path in technician_paths:
            path.append(0)

        # After this step, some technician paths may still be empty (i.e. [0, 0]), just leave them unchanged

        # Serve all dronable waypoints
        drone_paths = [[[0]] for _ in range(cls.drones_count)]
        dronable = set(e for e in range(1, 1 + cls.customers_count) if cls.dronable[e])

        drone_iter = itertools.cycle(range(cls.drones_count))
        while len(dronable) > 0:
            drone = next(drone_iter)
            paths = drone_paths[drone]
            config = cls.drone_linear_config[drone] if cls.energy_mode == DroneEnergyConsumptionMode.LINEAR else cls.drone_nonlinear_config[drone]

            path = paths[-1]
            index = min(dronable, key=partial(cls.distance, path[-1]))

            hypothetical_path = path + [index, 0]
            hypothetical_arrival_timestamps = cls.calculate_drone_arrival_timestamps(hypothetical_path, drone=drone, offset=0.0)
            if (
                cls.calculate_total_weight(hypothetical_path) > config.capacity
                or cls.calculate_drone_flight_duration(hypothetical_path, drone=drone, arrival_timestamps=hypothetical_arrival_timestamps) > cls.drones_flight_duration
                or cls.calculate_drone_energy_consumption(hypothetical_path, drone=drone, arrival_timestamps=hypothetical_arrival_timestamps) > config.battery
            ):
                path.append(0)
                paths.append([0])

                technician_path = min(technician_paths, key=lambda path: cls.distance(index, path[-2]))
                technician_path.insert(-1, index)

            else:
                path.append(index)

            dronable.remove(index)

        for paths in drone_paths:
            paths[-1].append(0)

        return cls(
            drone_paths=tuple(tuple(tuple(path) for path in paths if len(path) > 2) for paths in drone_paths),
            technician_paths=tuple(tuple(path) for path in technician_paths),
        )

    @classmethod
    def import_config(cls) -> None:
        cls.truck_config = TruckConfig.import_data()
        cls.drone_linear_config = DroneLinearConfig.import_data()
        cls.drone_nonlinear_config = DroneNonlinearConfig.import_data()
        cls.drone_endurance_config = DroneEnduranceConfig.import_data()

    @classmethod
    def import_problem(cls, problem: str, *, energy_mode: DroneEnergyConsumptionMode = DroneEnergyConsumptionMode.LINEAR) -> None:
        if not cls.__config_imported:
            cls.import_config()
            cls.__config_imported = True

        try:
            problem = problem.removesuffix(".txt")
            path = join("problems", "d2d", "random_data", f"{problem}.txt")
            with open(path, "r") as file:
                data = file.read()

            cls.problem = problem
            cls.customers_count = int(re.search(r"Customers (\d+)", data).group(1))  # type: ignore
            cls.drones_count = int(re.search(r"number_drone (\d+)", data).group(1))  # type: ignore
            cls.technicians_count = int(re.search(r"number_drone (\d+)", data).group(1))  # type: ignore
            cls.drones_flight_duration = float(re.search(r"droneLimitationFightTime\(s\) (\d+)", data).group(1))  # type: ignore

            cls_x = [0.0]
            cls_y = [0.0]
            cls_demands = [0.0]
            cls_dronable = [True]
            cls_technician_service_time = [0.0]
            cls_drone_service_time = [0.0]
            for match in re.finditer(r"([-\d\.]+)\s+([-\d\.]+)\s+([\d\.]+)\s+(0|1)\t([\d\.]+)\s+([\d\.]+)", data):
                x, y, demand, technician_only, technician_service_time, drone_service_time = match.groups()
                cls_x.append(float(x))
                cls_y.append(float(y))
                cls_demands.append(float(demand))
                cls_dronable.append(technician_only == "0")
                cls_technician_service_time.append(float(technician_service_time))
                cls_drone_service_time.append(float(drone_service_time))

            cls.x = tuple(cls_x)
            cls.y = tuple(cls_y)
            cls.demands = tuple(cls_demands)
            cls.dronable = tuple(cls_dronable)
            cls.technician_service_time = tuple(cls_technician_service_time)
            cls.drone_service_time = tuple(cls_drone_service_time)

            cls.energy_mode = energy_mode

        except Exception as e:
            raise ImportException(problem) from e

    def __hash__(self) -> int:
        return hash((self.drone_paths, self.technician_paths))
