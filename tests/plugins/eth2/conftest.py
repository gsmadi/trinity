import pytest
from eth2.beacon.tools.misc.ssz_vector import (
    override_vector_lengths,
)
from eth2.beacon.state_machines.forks.xiao_long_bao.configs import (
    XIAO_LONG_BAO_CONFIG,
)


# SSZ
@pytest.fixture(scope="function", autouse=True)
def override_lengths():
    override_vector_lengths(XIAO_LONG_BAO_CONFIG)
