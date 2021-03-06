# Lint as: python3
# Copyright 2020 DeepMind Technologies Limited. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for `asserts.py`."""

import functools
from absl.testing import absltest
from absl.testing import parameterized
from chex._src import asserts
from chex._src import variants
import jax
import jax.numpy as jnp
import numpy as np


def as_arrays(arrays):
  return [np.asarray(a) for a in arrays]


def emplace(arrays):
  return arrays


class AssertMaxTracesTest(variants.TestCase):

  def _init(self, fn_, init_type, max_traces, kwargs, static_arg):
    variant_kwargs = dict()
    if static_arg:
      variant_kwargs['static_argnums'] = 1

    if kwargs:
      args, kwargs = list(), dict(n=max_traces)
    else:
      args, kwargs = [max_traces], dict()

    if init_type == 't1':

      @asserts.assert_max_traces(*args, **kwargs)
      def fn(x, y):
        if static_arg:
          self.assertNotIsInstance(y, jax.core.Tracer)
        return fn_(x, y)

      fn_jitted = self.variant(fn, **variant_kwargs)
    elif init_type == 't2':

      def fn(x, y):
        if static_arg:
          self.assertNotIsInstance(y, jax.core.Tracer)
        return fn_(x, y)

      fn = asserts.assert_max_traces(fn, *args, **kwargs)
      fn_jitted = self.variant(fn, **variant_kwargs)
    elif init_type == 't3':

      def fn(x, y):
        if static_arg:
          self.assertNotIsInstance(y, jax.core.Tracer)
        return fn_(x, y)

      @self.variant(**variant_kwargs)
      @asserts.assert_max_traces(*args, **kwargs)
      def fn_jitted(x, y):
        self.assertIsInstance(x, jax.core.Tracer)
        return fn_(x, y)
    else:
      raise ValueError(f'Unknown type {init_type}.')

    return fn, fn_jitted

  @variants.variants(with_jit=True, with_pmap=True)
  @parameterized.named_parameters(
      variants.params_product((
          ('type1', 't1'),
          ('type2', 't2'),
          ('type3', 't3'),
      ), (
          ('args', False),
          ('kwargs', True),
      ), (
          ('no_static_arg', False),
          ('with_static_arg', True),
      ), (
          ('max_traces_0', 0),
          ('max_traces_1', 1),
          ('max_traces_2', 2),
          ('max_traces_10', 10),
      ),
                              named=True))
  def test_assert(self, init_type, kwargs, static_arg, max_traces):
    fn_ = lambda x, y: x + y
    fn, fn_jitted = self._init(fn_, init_type, max_traces, kwargs, static_arg)

    # Original function.
    for _ in range(max_traces + 3):
      self.assertEqual(fn(1, 2), 3)

    # Every call results in re-tracing because arguments' shapes are different.
    for i in range(max_traces):
      for k in range(5):
        arg = jnp.zeros(i + 1) + k
        np.testing.assert_array_equal(fn_jitted(arg, 2), arg + 2)

    # Original function.
    for _ in range(max_traces + 3):
      self.assertEqual(fn(1, 2), 3)
      self.assertEqual(fn([1], [2]), [1, 2])
      self.assertEqual(fn('a', 'b'), 'ab')

    # (max_traces + 1)-th re-tracing.
    with self.assertRaisesRegex(AssertionError, 'fn.* is traced > .* times!'):
      arg = jnp.zeros(max_traces + 1)
      fn_jitted(arg, 2)

  def test_incorrect_ordering(self):
    # pylint:disable=g-error-prone-assert-raises,unused-variable
    with self.assertRaisesRegex(ValueError, 'change wrappers ordering'):

      @asserts.assert_max_traces(1)
      @jax.jit
      def fn(_):
        pass

    def dummy_wrapper(fn):

      @functools.wraps(fn)
      def fn_wrapped():
        return fn()

      return fn_wrapped

    with self.assertRaisesRegex(ValueError, 'change wrappers ordering'):

      @asserts.assert_max_traces(1)
      @dummy_wrapper
      @jax.jit
      def fn_2():
        pass

    # pylint:enable=g-error-prone-assert-raises,unused-variable


class ScalarAssertTest(parameterized.TestCase):

  def test_scalar(self):
    asserts.assert_scalar(1)
    asserts.assert_scalar(1.)
    with self.assertRaisesRegex(AssertionError, 'must be a scalar'):
      asserts.assert_scalar(np.array(1.))  # pytype: disable=wrong-arg-types

  def test_scalar_positive(self):
    asserts.assert_scalar_positive(0.5)
    with self.assertRaisesRegex(AssertionError, 'must be positive'):
      asserts.assert_scalar_positive(-0.5)

  def test_scalar_non_negative(self):
    asserts.assert_scalar_non_negative(0.5)
    asserts.assert_scalar_non_negative(0.)
    with self.assertRaisesRegex(AssertionError, 'must be non negative'):
      asserts.assert_scalar_non_negative(-0.5)

  def test_scalar_negative(self):
    asserts.assert_scalar_negative(-0.5)
    with self.assertRaisesRegex(AssertionError, 'argument must be negative'):
      asserts.assert_scalar_negative(0.5)

  def test_scalar_in(self):
    asserts.assert_scalar_in(0.5, 0, 1)
    with self.assertRaisesRegex(AssertionError, 'argument must be in'):
      asserts.assert_scalar_in(-0.5, 0, 1)
    with self.assertRaisesRegex(AssertionError, 'argument must be in'):
      asserts.assert_scalar_in(1.5, 0, 1)

  def test_scalar_in_excluded(self):
    asserts.assert_scalar_in(0.5, 0, 1, included=False)
    with self.assertRaisesRegex(AssertionError, 'argument must be in'):
      asserts.assert_scalar_in(0, 0, 1, included=False)
    with self.assertRaisesRegex(AssertionError, 'argument must be in'):
      asserts.assert_scalar_in(1, 0, 1, included=False)


class EqualShapeAssertTest(parameterized.TestCase):

  @parameterized.named_parameters(
      ('not_scalar', [1, 2, [3]]),
      ('wrong_rank', [[1], [2], 3]),
      ('wrong_length', [[1], [2], [3, 4]]),
  )
  def test_equal_shape_should_fail(self, arrays):
    arrays = as_arrays(arrays)
    with self.assertRaisesRegex(AssertionError, 'Arrays have different shapes'):
      asserts.assert_equal_shape(arrays)

  @parameterized.named_parameters(
      ('scalars', [1, 2, 3]),
      ('vectors', [[1], [2], [3]]),
      ('matrices', [[[1], [2]], [[3], [4]]]),
  )
  def test_equal_shape_should_pass(self, arrays):
    arrays = as_arrays(arrays)
    asserts.assert_equal_shape(arrays)


class ShapeAssertTest(parameterized.TestCase):

  @parameterized.named_parameters(
      ('wrong_rank', [1], (1,)),
      ('wrong_shape', [1, 2], (1, 3)),
      ('some_wrong_shape', [[1, 2], [3, 4]], [(1, 2), (1, 3)]),
      ('wrong_common_shape', [[1, 2], [3, 4, 3]], (2,)),
      ('wrong_common_shape_2', [[1, 2, 3], [1, 2]], (2,)),
  )
  def test_shape_should_fail(self, arrays, shapes):
    arrays = as_arrays(arrays)
    with self.assertRaisesRegex(AssertionError,
                                'input .+ has shape .+ but expected .+'):
      asserts.assert_shape(arrays, shapes)

  @parameterized.named_parameters(
      ('too_many_shapes', [[1]], [(1,), (2,)]),
      ('not_enough_shapes', [[1, 2], [3, 4]], [(3,)]),
  )
  def test_shape_should_fail_wrong_length(self, arrays, shapes):
    arrays = as_arrays(arrays)
    with self.assertRaisesRegex(
        AssertionError, 'Length of `inputs` and `expected_shapes` must match'):
      asserts.assert_shape(arrays, shapes)

  @parameterized.named_parameters(
      ('scalars', [1, 2], ()),
      ('vectors', [[1, 2], [3, 4, 5]], [(2,), (3,)]),
      ('matrices', [[[1, 2], [3, 4]]], (2, 2)),
      ('vectors_common_shape', [[1, 2], [3, 4]], (2,)),
  )
  def test_shape_should_pass(self, arrays, shapes):
    arrays = as_arrays(arrays)
    asserts.assert_shape(arrays, shapes)


def rank_array(n):
  return np.zeros(shape=[2] * n)


class RankAssertTest(parameterized.TestCase):

  def test_rank_should_fail_array_expectations(self):
    with self.assertRaisesRegex(  # pylint: disable=g-error-prone-assert-raises
        ValueError,
        'expected ranks should be a collection of integers but was an array'):
      asserts.assert_rank(rank_array(2), np.array([2]))

  def test_rank_should_fail_wrong_expectation_structure(self):
    with self.assertRaisesRegex(  # pylint: disable=g-error-prone-assert-raises
        ValueError, 'Expected ranks should be integers or sets of integers'):
      asserts.assert_rank(rank_array(2), [[1, 2]])  # pytype: disable=wrong-arg-types

    with self.assertRaisesRegex(  # pylint: disable=g-error-prone-assert-raises
        ValueError, 'Expected ranks should be integers or sets of integers'):
      asserts.assert_rank([rank_array(1), rank_array(2)], [[1], [2]])  # pytype: disable=wrong-arg-types

  @parameterized.named_parameters(
      ('rank_1', rank_array(1), 2),
      ('rank_2', rank_array(2), 1),
      ('rank_3', rank_array(3), {2, 4}),
  )
  def test_rank_should_fail_single(self, array, rank):
    array = np.asarray(array)
    with self.assertRaisesRegex(AssertionError,
                                'input .+ has rank .+ but expected .+'):
      asserts.assert_rank(array, rank)

  @parameterized.named_parameters(
      ('wrong_1', [rank_array(1), rank_array(2)], [2, 2]),
      ('wrong_2', [rank_array(1), rank_array(2)], [1, 3]),
      ('wrong_3', [rank_array(1), rank_array(2)], [{2, 3}, 2]),
      ('wrong_4', [rank_array(1), rank_array(2)], [1, {1, 3}]),
  )
  def test_assert_rank_should_fail_sequence(self, arrays, ranks):
    arrays = as_arrays(arrays)
    with self.assertRaisesRegex(AssertionError,
                                'input .+ has rank .+ but expected .+'):
      asserts.assert_rank(arrays, ranks)

  @parameterized.named_parameters(
      ('not_enough_ranks', [1, 3, 4], [1, 1]),
      ('too_many_ranks', [1, 2], [1, 1, 1]),
  )
  def test_rank_should_fail_wrong_length(self, array, rank):
    array = np.asarray(array)
    with self.assertRaisesRegex(
        AssertionError, 'Length of inputs and expected_ranks must match.'):
      asserts.assert_rank(array, rank)

  @parameterized.named_parameters(
      ('rank_1', rank_array(1), 1),
      ('rank_2', rank_array(2), 2),
      ('rank_3', rank_array(3), {1, 2, 3}),
  )
  def test_rank_should_pass_single_input(self, array, rank):
    array = np.asarray(array)
    asserts.assert_rank(array, rank)

  @parameterized.named_parameters(
      ('rank_1', rank_array(1), 1),
      ('rank_2', rank_array(2), 2),
      ('rank_3', rank_array(3), {1, 2, 3}),
  )
  def test_rank_should_pass_repeated_input(self, array, rank):
    arrays = as_arrays([array] * 3)
    asserts.assert_rank(arrays, rank)

  @parameterized.named_parameters(
      ('single_option', [rank_array(1), rank_array(2)], {1, 2}),
      ('seq_options_1', [rank_array(1), rank_array(2)], [{1, 2}, 2]),
      ('seq_options_2', [rank_array(1), rank_array(2)], [1, {1, 2}]),
  )
  def test_rank_should_pass_multiple_options(self, arrays, ranks):
    arrays = as_arrays(arrays)
    asserts.assert_rank(arrays, ranks)


class TypeAssertTest(parameterized.TestCase):

  @parameterized.named_parameters(
      ('one_float', 3., int),
      ('one_int', 3, float),
      ('many_floats', [1., 2., 3.], int),
      ('many_floats_verbose', [1., 2., 3.], [float, float, int]),
  )
  def test_type_should_fail_scalar(self, scalars, wrong_type):
    with self.assertRaisesRegex(AssertionError,
                                'input .+ has type .+ but expected .+'):
      asserts.assert_type(scalars, wrong_type)

  @variants.variants(with_device=True, without_device=True)
  @parameterized.named_parameters(
      ('one_float_array', [1., 2.], int),
      ('one_int_array', [1, 2], float),
  )
  def test_type_should_fail_array(self, array, wrong_type):
    array = self.variant(emplace)(array)
    with self.assertRaisesRegex(AssertionError,
                                'input .+ has type .+ but expected .+'):
      asserts.assert_type(array, wrong_type)

  @parameterized.named_parameters(
      ('one_float', 3., float),
      ('one_int', 3, int),
      ('many_floats', [1., 2., 3.], float),
      ('many_floats_verbose', [1., 2., 3.], [float, float, float]),
  )
  def test_type_should_pass_scalar(self, array, wrong_type):
    asserts.assert_type(array, wrong_type)

  @variants.variants(with_device=True, without_device=True)
  @parameterized.named_parameters(
      ('one_float_array', [1., 2.], float),
      ('one_int_array', [1, 2], int),
  )
  def test_type_should_pass_array(self, array, wrong_type):
    array = self.variant(emplace)(array)
    asserts.assert_type(array, wrong_type)

  def test_type_should_fail_mixed(self):
    a_float = 1.
    an_int = 2
    a_np_float = np.asarray([3., 4.])
    a_jax_int = jnp.asarray([5, 6])
    with self.assertRaisesRegex(AssertionError,
                                'input .+ has type .+ but expected .+'):
      asserts.assert_type([a_float, an_int, a_np_float, a_jax_int],
                          [float, int, float, float])

  def test_type_should_pass_mixed(self):
    a_float = 1.
    an_int = 2
    a_np_float = np.asarray([3., 4.])
    a_jax_int = jnp.asarray([5, 6])
    asserts.assert_type([a_float, an_int, a_np_float, a_jax_int],
                        [float, int, float, int])

  @parameterized.named_parameters(
      ('too_many_types', [1., 2], [float, int, float]),
      ('not_enough_types', [1., 2], [float]),
  )
  def test_type_should_fail_wrong_length(self, array, wrong_type):
    with self.assertRaisesRegex(
        AssertionError, 'Length of `inputs` and `expected_types` must match:'):
      asserts.assert_type(array, wrong_type)

  def test_type_should_fail_unsupported_dtype(self):
    a_float = 1.
    an_int = 2
    a_np_float = np.asarray([3., 4.])
    a_jax_int = jnp.asarray([5, 6])
    with self.assertRaisesRegex(AssertionError, 'unsupported dtype'):
      asserts.assert_type([a_float, an_int, a_np_float, a_jax_int],
                          [np.complex, np.complex, float, int])


class AxisDimensionAssertionsTest(parameterized.TestCase):

  def test_assert_axis_dimension_pass(self):
    tensor = jnp.ones((3, 2, 7, 2))
    for i, s in enumerate(tensor.shape):
      asserts.assert_axis_dimension(tensor, axis=i, expected=s)

  def test_assert_axis_dimension_fail(self):
    tensor = jnp.ones((3, 2, 7, 2))
    for i, s in enumerate(tensor.shape):
      with self.assertRaisesRegex(
          AssertionError, 'Expected tensor to have dimension'):
        asserts.assert_axis_dimension(tensor, axis=i, expected=s+1)

  def test_assert_axis_invalid(self):
    tensor = jnp.ones((3, 2))
    with self.assertRaisesRegex(AssertionError, 'not available'):
      asserts.assert_axis_dimension(tensor, axis=2, expected=1)


class TreeAssertionsTest(parameterized.TestCase):

  def test_tree_all_finite_passes_finite(self):
    finite_tree = {'a': jnp.ones((3,)), 'b': jnp.array([0.0, 0.0])}
    asserts.assert_tree_all_finite(finite_tree)

  def test_tree_all_finite_should_fail_inf(self):
    inf_tree = {
        'finite_var': jnp.ones((3,)),
        'inf_var': jnp.array([0.0, jnp.inf]),
    }
    with self.assertRaisesRegex(AssertionError,
                                'Tree contains non-finite value'):
      asserts.assert_tree_all_finite(inf_tree)

  def test_assert_tree_all_close_passes_same_tree(self):
    tree1 = {
        'a': [jnp.zeros((1,))],
        'b': ([0], (0,), 0),
    }
    asserts.assert_tree_all_close(tree1, tree1)

  def test_assert_tree_all_close_passes_values_equal(self):
    tree1 = (jnp.array([0.0, 0.0]),)
    tree2 = (jnp.array([0.0, 0.0]),)
    asserts.assert_tree_all_close(tree1, tree2)

  def test_assert_tree_all_close_passes_values_close(self):
    tree1 = (jnp.array([1.0, 1.0]),)
    tree2 = (jnp.array([1.0, 1.0 + 1e-9]),)
    asserts.assert_tree_all_close(tree1, tree2)

  def test_assert_tree_all_close_fails_number_of_leaves(self):
    tree1 = (jnp.zeros((4,)), jnp.zeros((4,)))
    tree2 = (jnp.zeros((4,)))
    with self.assertRaisesRegex(
        AssertionError,
        'Error in value equality check: Trees do not have the same structure'):
      asserts.assert_tree_all_close(tree1, tree2)

  def test_assert_tree_all_close_fails_different_structure(self):
    val = jnp.zeros((4,))
    tree1 = ((val, val), val)
    tree2 = (val, (val, val))
    with self.assertRaisesRegex(
        AssertionError,
        'Error in value equality check: Trees do not have the same structure'):
      asserts.assert_tree_all_close(tree1, tree2)

  def test_assert_tree_all_close_fails_values_differ(self):
    tree1 = (jnp.array([0.0, 2.0]))
    tree2 = (jnp.array([0.0, 2.1]))
    asserts.assert_tree_all_close(tree1, tree2, atol=0.1)
    with self.assertRaisesRegex(AssertionError,
                                'Values not approximately equal'):
      asserts.assert_tree_all_close(tree1, tree2, atol=0.01)

    asserts.assert_tree_all_close(tree1, tree2, rtol=0.1)
    with self.assertRaisesRegex(AssertionError,
                                'Values not approximately equal'):
      asserts.assert_tree_all_close(tree1, tree2, rtol=0.01)


class NumDevicesAssertTest(parameterized.TestCase):

  def _device_count(self, backend):
    try:
      return jax.device_count(backend)
    except RuntimeError:
      return 0

  @parameterized.parameters('cpu', 'gpu', 'tpu')
  def test_not_less_than(self, devtype):
    n = self._device_count(devtype)
    if n > 0:
      asserts.assert_devices_available(
          n - 1, devtype, backend=devtype, not_less_than=True)
      with self.assertRaisesRegex(AssertionError, f'Only {n} < {n + 1}'):
        asserts.assert_devices_available(
            n + 1, devtype, backend=devtype, not_less_than=True)
    else:
      with self.assertRaisesRegex(RuntimeError, 'Unknown backend'):  # pylint: disable=g-error-prone-assert-raises
        asserts.assert_devices_available(
            n - 1, devtype, backend=devtype, not_less_than=True)

  def test_unsupported_device(self):
    with self.assertRaisesRegex(ValueError, 'Unknown device type'):  # pylint: disable=g-error-prone-assert-raises
      asserts.assert_devices_available(1, 'unsupported_devtype')

  def test_gpu_assert(self):
    n_gpu = self._device_count('gpu')
    asserts.assert_devices_available(n_gpu, 'gpu')
    if n_gpu:
      asserts.assert_gpu_available()
    else:
      with self.assertRaisesRegex(AssertionError, 'No 2 GPUs available'):
        asserts.assert_devices_available(2, 'gpu')
      with self.assertRaisesRegex(AssertionError, 'No GPU devices available'):
        asserts.assert_gpu_available()

    with self.assertRaisesRegex(AssertionError, 'No 2 GPUs available'):
      asserts.assert_devices_available(2, 'gpu', backend='cpu')

  def test_cpu_assert(self):
    n_cpu = jax.device_count('cpu')
    asserts.assert_devices_available(n_cpu, 'cpu', backend='cpu')

  def test_tpu_assert(self):
    n_tpu = self._device_count('tpu')
    asserts.assert_devices_available(n_tpu, 'tpu')
    if n_tpu:
      asserts.assert_tpu_available()
    else:
      with self.assertRaisesRegex(AssertionError, 'No 3 TPUs available'):
        asserts.assert_devices_available(3, 'tpu')
      with self.assertRaisesRegex(AssertionError, 'No TPU devices available'):
        asserts.assert_tpu_available()
    with self.assertRaisesRegex(AssertionError, 'No 3 TPUs available'):
      asserts.assert_devices_available(3, 'tpu', backend='cpu')


class NumericalGradsAssertTest(parameterized.TestCase):

  def _test_fn(self, fn, init_args, seed, n=10):
    rng_key = jax.random.PRNGKey(seed)
    for _ in range(n):
      rng_key, *tree_keys = jax.random.split(rng_key, len(init_args) + 1)
      x = jax.tree_multimap(lambda k, x: jax.random.uniform(k, shape=x.shape),
                            list(tree_keys), list(init_args))
      asserts.assert_numerical_grads(fn, x, order=1)

  @parameterized.parameters(([1], 24), ([5], 6), ([3, 5], 20))
  def test_easy(self, x_shape, seed):
    f_easy = lambda x: jnp.sum(x**2 - 2 * x + 10)
    init_args = (jnp.zeros(x_shape),)
    self._test_fn(f_easy, init_args, seed)

  @parameterized.parameters(([1], 24), ([5], 6), ([3, 5], 20))
  def test_easy_with_stop_gradient(self, x_shape, seed):
    f_easy_sg = lambda x: jnp.sum(jax.lax.stop_gradient(x**2) - 2 * x + 10)
    init_args = (jnp.zeros(x_shape),)
    self._test_fn(f_easy_sg, init_args, seed)

  @parameterized.parameters(([1], 24), ([5], 6), ([3, 5], 20))
  def test_hard(self, x_shape, seed):

    def f_hard_with_sg(lr, x):
      inner_loss = lambda y: jnp.sum((y - 1.0)**2)
      inner_loss_grad = jax.grad(inner_loss)

      def fu(lr, x):
        for _ in range(10):
          x1 = x - lr * inner_loss_grad(x) + 100 * lr**2
          x2 = x - lr * inner_loss_grad(x) - 100 * lr**2
          x = jax.lax.select((x > 3.).any(), x1, x2 + lr)
        return x

      y = fu(lr, x)
      return jnp.sum(inner_loss(y))

    lr = jnp.zeros([1] * len(x_shape))
    x = jnp.zeros(x_shape)

    self._test_fn(f_hard_with_sg, (lr, x), seed)

  @parameterized.parameters(([1], 24), ([5], 6), ([3, 5], 20))
  def test_hard_with_stop_gradient(self, x_shape, seed):

    def f_hard_with_sg(lr, x):
      inner_loss = lambda y: jnp.sum((y - 1.0)**2)
      inner_loss_grad = jax.grad(inner_loss)

      def fu(lr, x):
        for _ in range(10):
          x1 = x - lr * inner_loss_grad(x) + 100 * jax.lax.stop_gradient(lr)**2
          x2 = x - lr * inner_loss_grad(x) - 100 * lr**2
          x = jax.lax.select((x > 3.).any(), x1, x2 + jax.lax.stop_gradient(lr))
        return x

      y = fu(lr, x)
      return jnp.sum(inner_loss(y))

    lr = jnp.zeros([1] * len(x_shape))
    x = jnp.zeros(x_shape)

    self._test_fn(f_hard_with_sg, (lr, x), seed)


class EqualAssertionsTest(parameterized.TestCase):

  @parameterized.named_parameters(
      ('dtypes', jnp.int32, jnp.int32),
      ('lists', [1, 2], [1, 2]),
      ('dicts', dict(a=[7, jnp.int32]), dict(a=[7, jnp.int32])),
  )
  def test_assert_equal_pass(self, first, second):
    asserts.assert_equal(first, second)

  def test_assert_equal_pass_on_arrays(self):
    # Not using named_parameters, becase JAX cannot be used before app.run().
    asserts.assert_equal(jnp.ones([]), np.ones([]))
    asserts.assert_equal(jnp.ones([], dtype=jnp.int32),
                         np.ones([], dtype=np.float64))

  @parameterized.named_parameters(
      ('dtypes', jnp.int32, jnp.float32),
      ('lists', [1, 2], [1, 7]),
      ('lists2', [1, 2], [1]),
      ('dicts1', dict(a=[7, jnp.int32]), dict(b=[7, jnp.int32])),
      ('dicts2', dict(a=[7, jnp.int32]), dict(b=[1, jnp.int32])),
      ('dicts3', dict(a=[7, jnp.int32]), dict(a=[1, jnp.int32], b=2)),
      ('dicts4', dict(a=[7, jnp.int32]), dict(a=[1, jnp.float32])),
      ('arrays', np.zeros([]), np.ones([])),
  )
  def test_assert_equal_fail(self, first, second):
    with self.assertRaises(AssertionError):
      asserts.assert_equal(first, second)


if __name__ == '__main__':
  jax.config.update('jax_numpy_rank_promotion', 'raise')
  absltest.main()
