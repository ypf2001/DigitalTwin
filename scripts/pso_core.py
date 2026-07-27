"""Generic Particle Swarm Optimization (PSO) algorithm.

Independent of any domain — takes a black-box objective function and returns
the best position found.  Configurable swarm size, inertia decay, cognitive and
social coefficients, and early stopping.

Usage::

    bounds = [(30, 600), (30, 900), (0, 0.5)]  # lambda_EC, lambda_pH, beta
    pso = PSO(bounds, n_particles=30, max_iter=100, seed=42)
    result = pso.optimize(lambda x: evaluate(x))
    print(result.best_position, result.best_cost)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np


@dataclass
class PSOResult:
    best_position: np.ndarray
    best_cost: float
    convergence: list[float]  # best_cost per generation
    mean_costs: list[float]   # mean cost per generation
    generations: int
    early_stopped: bool
    elapsed_s: float


class PSO:
    """Particle Swarm Optimizer.

    Parameters
    ----------
    bounds : sequence of (low, high) tuples
        Search bounds for each dimension.
    n_particles : int
        Swarm size (default 30).
    max_iter : int
        Maximum generations (default 100).
    w_start : float
        Initial inertia weight (default 0.9).
    w_end : float
        Final inertia weight (default 0.4).
    c1 : float
        Cognitive coefficient (default 2.0).
    c2 : float
        Social coefficient (default 2.0).
    early_stop_tol : float
        Stop if best cost improves less than this over ``patience`` generations.
    patience : int
        Number of generations to wait before early stopping (default 20).
    seed : int or None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        bounds: Sequence[tuple[float, float]],
        n_particles: int = 30,
        max_iter: int = 100,
        w_start: float = 0.9,
        w_end: float = 0.4,
        c1: float = 2.0,
        c2: float = 2.0,
        early_stop_tol: float = 1e-4,
        patience: int = 20,
        seed: int | None = None,
    ):
        self.bounds = np.array(bounds, dtype=np.float64)
        self.n_dims = len(bounds)
        self.n_particles = n_particles
        self.max_iter = max_iter
        self.w_start = float(w_start)
        self.w_end = float(w_end)
        self.c1 = float(c1)
        self.c2 = float(c2)
        self.early_stop_tol = float(early_stop_tol)
        self.patience = int(patience)
        self._rng = np.random.default_rng(seed)

        # Pre-compute velocity clamp (±20% of search range)
        ranges = self.bounds[:, 1] - self.bounds[:, 0]
        self._v_max = 0.2 * ranges
        self._v_clamp = np.column_stack([-self._v_max, self._v_max])

    def _init_swarm(self):
        """Randomly initialise particle positions and velocities within bounds."""
        low = self.bounds[:, 0]
        high = self.bounds[:, 1]
        self.positions = self._rng.uniform(low, high, size=(self.n_particles, self.n_dims))
        self.velocities = self._rng.uniform(
            -self._v_max, self._v_max, size=(self.n_particles, self.n_dims)
        )
        self.personal_best_pos = self.positions.copy()
        self.personal_best_cost = np.full(self.n_particles, np.inf)
        self.global_best_pos = self.positions[0].copy()
        self.global_best_cost = np.inf

    def _w(self, gen: int) -> float:
        """Linear inertia decay."""
        if self.max_iter <= 1:
            return self.w_end
        return self.w_start - (self.w_start - self.w_end) * gen / (self.max_iter - 1)

    def optimize(self, objective: Callable[[np.ndarray], float],
                 callback: Callable[[int, np.ndarray, float, float, list[float]], None] | None = None,
                 ) -> PSOResult:
        """Run PSO.

        Parameters
        ----------
        objective : callable
            Function that takes a position vector and returns a scalar cost.
            Should return ``inf`` for infeasible solutions.
        callback : callable, optional
            Called after each generation: callback(gen, best_pos, best_cost, mean_cost, all_costs).

        Returns
        -------
        PSOResult
        """
        t0 = time.perf_counter()
        self._init_swarm()

        convergence: list[float] = []
        mean_costs: list[float] = []
        stagnant_gens = 0
        prev_best = np.inf

        for gen in range(self.max_iter):
            w = self._w(gen)
            costs = np.full(self.n_particles, np.inf)

            # Evaluate all particles
            for i in range(self.n_particles):
                costs[i] = objective(self.positions[i])

            # Update personal and global bests
            improved = costs < self.personal_best_cost
            self.personal_best_cost[improved] = costs[improved]
            self.personal_best_pos[improved] = self.positions[improved].copy()

            gen_best_idx = np.argmin(costs)
            if costs[gen_best_idx] < self.global_best_cost:
                self.global_best_cost = costs[gen_best_idx]
                self.global_best_pos = self.positions[gen_best_idx].copy()

            convergence.append(self.global_best_cost)
            mean_costs.append(float(np.mean(costs[np.isfinite(costs)])))

            if callback is not None:
                callback(gen, self.global_best_pos.copy(), self.global_best_cost,
                         mean_costs[-1], costs.tolist())

            # Velocity update
            r1 = self._rng.uniform(0, 1, size=(self.n_particles, self.n_dims))
            r2 = self._rng.uniform(0, 1, size=(self.n_particles, self.n_dims))
            cognitive = self.c1 * r1 * (self.personal_best_pos - self.positions)
            social = self.c2 * r2 * (self.global_best_pos - self.positions)
            self.velocities = w * self.velocities + cognitive + social

            # Clamp velocity
            self.velocities = np.clip(self.velocities, self._v_clamp[:, 0], self._v_clamp[:, 1])

            # Update positions
            new_positions = self.positions + self.velocities

            # Boundary handling: clamp + zero velocity
            for d in range(self.n_dims):
                below = new_positions[:, d] < self.bounds[d, 0]
                above = new_positions[:, d] > self.bounds[d, 1]
                new_positions[below, d] = self.bounds[d, 0]
                new_positions[above, d] = self.bounds[d, 1]
                self.velocities[below | above, d] = 0.0

            self.positions = new_positions

            # Early stopping
            if abs(self.global_best_cost - prev_best) < self.early_stop_tol:
                stagnant_gens += 1
            else:
                stagnant_gens = 0
            prev_best = self.global_best_cost

            if stagnant_gens >= self.patience:
                elapsed = time.perf_counter() - t0
                return PSOResult(
                    best_position=self.global_best_pos,
                    best_cost=self.global_best_cost,
                    convergence=convergence,
                    mean_costs=mean_costs,
                    generations=gen + 1,
                    early_stopped=True,
                    elapsed_s=elapsed,
                )

        elapsed = time.perf_counter() - t0
        return PSOResult(
            best_position=self.global_best_pos,
            best_cost=self.global_best_cost,
            convergence=convergence,
            mean_costs=mean_costs,
            generations=self.max_iter,
            early_stopped=False,
            elapsed_s=elapsed,
        )
