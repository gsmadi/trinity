from typing import (
    Iterable,
    Sequence,
    Tuple,
    TYPE_CHECKING,
)

from eth_utils import (
    to_tuple,
    ValidationError,
)
from eth_typing import (
    Hash32,
)

from eth2._utils.bitfield import (
    has_voted,
)
from eth2._utils.numeric import (
    is_power_of_two,
)
from eth2.beacon._utils.random import (
    shuffle,
    split,
)
from eth2.beacon.configs import (
    CommitteeConfig,
)
from eth2.beacon import helpers
from eth2.beacon.helpers import (
    get_active_validator_indices,
    slot_to_epoch,
)

from eth2.beacon.typing import (
    Bitfield,
    Epoch,
    Shard,
    Slot,
    ValidatorIndex,
)
from eth2.beacon.validation import (
    validate_bitfield,
    validate_epoch_for_current_epoch,
)

if TYPE_CHECKING:
    from eth2.beacon.types.attestation_data import AttestationData  # noqa: F401
    from eth2.beacon.types.states import BeaconState  # noqa: F401
    from eth2.beacon.types.validator_records import ValidatorRecord  # noqa: F401


def get_epoch_committee_count(
        active_validator_count: int,
        shard_count: int,
        slots_per_epoch: int,
        target_committee_size: int) -> int:
    return max(
        1,
        min(
            shard_count // slots_per_epoch,
            active_validator_count // slots_per_epoch // target_committee_size,
        )
    ) * slots_per_epoch


def get_shuffling(*,
                  seed: Hash32,
                  validators: Sequence['ValidatorRecord'],
                  epoch: Epoch,
                  slots_per_epoch: int,
                  target_committee_size: int,
                  shard_count: int) -> Tuple[Iterable[ValidatorIndex], ...]:
    """
    Shuffle ``validators`` into crosslink committees seeded by ``seed`` and ``epoch``.
    Return a list of ``committee_per_epoch`` committees where each
    committee is itself a list of validator indices.

    If ``get_shuffling(seed, validators, epoch)`` returns some value ``x`` for some
    ``epoch <= get_current_epoch(state) + ACTIVATION_EXIT_DELAY``, it should return the
    same value ``x`` for the same ``seed`` and ``epoch`` and possible future modifications
    of ``validators`` forever in phase 0, and until the ~1 year deletion delay in phase 2
    and in the future.
    """
    active_validator_indices = get_active_validator_indices(validators, epoch)

    committees_per_epoch = get_epoch_committee_count(
        len(active_validator_indices),
        shard_count,
        slots_per_epoch,
        target_committee_size,
    )

    # Shuffle
    shuffled_active_validator_indices = shuffle(active_validator_indices, seed)

    # Split the shuffled list into committees_per_epoch pieces
    return tuple(
        split(
            shuffled_active_validator_indices,
            committees_per_epoch,
        )
    )


def get_previous_epoch_committee_count(
        state: 'BeaconState',
        shard_count: int,
        slots_per_epoch: int,
        target_committee_size: int) -> int:
    previous_active_validators = get_active_validator_indices(
        state.validator_registry,
        state.previous_shuffling_epoch,
    )
    return get_epoch_committee_count(
        active_validator_count=len(previous_active_validators),
        shard_count=shard_count,
        slots_per_epoch=slots_per_epoch,
        target_committee_size=target_committee_size,
    )


def get_current_epoch_committee_count(
        state: 'BeaconState',
        shard_count: int,
        slots_per_epoch: int,
        target_committee_size: int) -> int:
    current_active_validators = get_active_validator_indices(
        state.validator_registry,
        state.current_shuffling_epoch,
    )
    return get_epoch_committee_count(
        active_validator_count=len(current_active_validators),
        shard_count=shard_count,
        slots_per_epoch=slots_per_epoch,
        target_committee_size=target_committee_size,
    )


def get_next_epoch_committee_count(
        state: 'BeaconState',
        shard_count: int,
        slots_per_epoch: int,
        target_committee_size: int) -> int:
    next_active_validators = get_active_validator_indices(
        state.validator_registry,
        state.current_shuffling_epoch + 1,
    )
    return get_epoch_committee_count(
        active_validator_count=len(next_active_validators),
        shard_count=shard_count,
        slots_per_epoch=slots_per_epoch,
        target_committee_size=target_committee_size,
    )


@to_tuple
def get_crosslink_committees_at_slot(
        state: 'BeaconState',
        slot: Slot,
        committee_config: CommitteeConfig,
        registry_change: bool=False) -> Iterable[Tuple[Iterable[ValidatorIndex], Shard]]:
    """
    Return the list of ``(committee, shard)`` tuples for the ``slot``.
    """
    genesis_epoch = committee_config.GENESIS_EPOCH
    shard_count = committee_config.SHARD_COUNT
    slots_per_epoch = committee_config.SLOTS_PER_EPOCH
    target_committee_size = committee_config.TARGET_COMMITTEE_SIZE

    min_seed_lookahead = committee_config.MIN_SEED_LOOKAHEAD
    activation_exit_delay = committee_config.ACTIVATION_EXIT_DELAY
    latest_active_index_roots_length = committee_config.LATEST_ACTIVE_INDEX_ROOTS_LENGTH
    latest_randao_mixes_length = committee_config.LATEST_RANDAO_MIXES_LENGTH

    epoch = slot_to_epoch(slot, slots_per_epoch)
    current_epoch = state.current_epoch(slots_per_epoch)
    previous_epoch = state.previous_epoch(slots_per_epoch, genesis_epoch)
    next_epoch = state.next_epoch(slots_per_epoch)

    validate_epoch_for_current_epoch(
        current_epoch=current_epoch,
        given_epoch=epoch,
        genesis_epoch=genesis_epoch,
    )

    if epoch == current_epoch:
        committees_per_epoch = get_current_epoch_committee_count(
            state=state,
            shard_count=shard_count,
            slots_per_epoch=slots_per_epoch,
            target_committee_size=target_committee_size,
        )
        seed = state.current_shuffling_seed
        shuffling_epoch = state.current_shuffling_epoch
        shuffling_start_shard = state.current_shuffling_start_shard
    elif epoch == previous_epoch:
        committees_per_epoch = get_previous_epoch_committee_count(
            state=state,
            shard_count=shard_count,
            slots_per_epoch=slots_per_epoch,
            target_committee_size=target_committee_size,
        )
        seed = state.previous_shuffling_seed
        shuffling_epoch = state.previous_shuffling_epoch
        shuffling_start_shard = state.previous_shuffling_start_shard
    elif epoch == next_epoch:
        current_committees_per_epoch = get_current_epoch_committee_count(
            state=state,
            shard_count=shard_count,
            slots_per_epoch=slots_per_epoch,
            target_committee_size=target_committee_size,
        )
        committees_per_epoch = get_next_epoch_committee_count(
            state=state,
            shard_count=shard_count,
            slots_per_epoch=slots_per_epoch,
            target_committee_size=target_committee_size,
        )
        shuffling_epoch = next_epoch
        epochs_since_last_registry_update = current_epoch - state.validator_registry_update_epoch
        should_reseed = (
            epochs_since_last_registry_update > 1 and
            is_power_of_two(epochs_since_last_registry_update)
        )

        if registry_change:
            # for mocking this out in tests.
            seed = helpers.generate_seed(
                state=state,
                epoch=next_epoch,
                slots_per_epoch=slots_per_epoch,
                min_seed_lookahead=min_seed_lookahead,
                activation_exit_delay=activation_exit_delay,
                latest_active_index_roots_length=latest_active_index_roots_length,
                latest_randao_mixes_length=latest_randao_mixes_length,
            )
            shuffling_start_shard = (
                state.current_shuffling_start_shard + current_committees_per_epoch
            ) % shard_count
        elif should_reseed:
            # for mocking this out in tests.
            seed = helpers.generate_seed(
                state=state,
                epoch=next_epoch,
                slots_per_epoch=slots_per_epoch,
                min_seed_lookahead=min_seed_lookahead,
                activation_exit_delay=activation_exit_delay,
                latest_active_index_roots_length=latest_active_index_roots_length,
                latest_randao_mixes_length=latest_randao_mixes_length,
            )
            shuffling_start_shard = state.current_shuffling_start_shard
        else:
            seed = state.current_shuffling_seed
            shuffling_start_shard = state.current_shuffling_start_shard

    shuffling = get_shuffling(
        seed=seed,
        validators=state.validator_registry,
        epoch=shuffling_epoch,
        slots_per_epoch=slots_per_epoch,
        target_committee_size=target_committee_size,
        shard_count=shard_count,
    )
    offset = slot % slots_per_epoch
    committees_per_slot = committees_per_epoch // slots_per_epoch
    slot_start_shard = (
        shuffling_start_shard +
        committees_per_slot * offset
    ) % shard_count

    for index in range(committees_per_slot):
        committee = shuffling[committees_per_slot * offset + index]
        yield (
            committee,
            Shard((slot_start_shard + index) % shard_count),
        )


def get_beacon_proposer_index(state: 'BeaconState',
                              slot: Slot,
                              committee_config: CommitteeConfig) -> ValidatorIndex:
    """
    Return the beacon proposer index for the ``slot``.
    """
    crosslink_committees_at_slot = get_crosslink_committees_at_slot(
        state=state,
        slot=slot,
        committee_config=committee_config,
    )
    try:
        first_crosslink_committee = crosslink_committees_at_slot[0]
    except IndexError:
        raise ValidationError("crosslink_committees should not be empty.")

    first_committee, _ = first_crosslink_committee
    if len(first_committee) <= 0:
        raise ValidationError(
            "The first committee should not be empty"
        )

    return first_committee[slot % len(first_committee)]


@to_tuple
def get_crosslink_committee_for_attestation(
        state: 'BeaconState',
        attestation_data: 'AttestationData',
        committee_config: CommitteeConfig) -> Iterable[ValidatorIndex]:
    """
    Return the specific crosslink committee concerning the given ``attestation_data``.
    In particular, the (slot, shard) coordinate in the ``attestation_data`` selects one committee
    from all committees expected to attest at the slot.

    Raise `ValidationError` in the case that this attestation references a shard that
    is not covered in the specified slot.
    """
    crosslink_committees = get_crosslink_committees_at_slot(
        state=state,
        slot=attestation_data.slot,
        committee_config=committee_config,
    )

    try:
        return next(
            committee for (
                committee,
                shard,
            ) in crosslink_committees if shard == attestation_data.shard
        )
    except StopIteration:
        raise ValidationError(
            "attestation_data.shard ({}) is not in crosslink_committees".format(
                attestation_data.shard,
            )
        )


@to_tuple
def get_members_from_bitfield(committee: Sequence[ValidatorIndex],
                              bitfield: Bitfield) -> Iterable[ValidatorIndex]:
    """
    Return all indices in ``committee`` if they "voted" according to the
    ``bitfield``.

    Raise ``ValidationError`` if the ``bitfield`` does not conform to some
    basic checks around length and zero-padding based on the ``committee``
    length.
    """
    validate_bitfield(bitfield, len(committee))

    # Extract committee members if the corresponding bit is set in the bitfield
    for bitfield_index, validator_index in enumerate(committee):
        if has_voted(bitfield, bitfield_index):
            yield validator_index


def get_attestation_participants(state: 'BeaconState',
                                 attestation_data: 'AttestationData',
                                 bitfield: Bitfield,
                                 committee_config: CommitteeConfig) -> Iterable[ValidatorIndex]:
    """
    Return the participant indices at for the ``attestation_data`` and ``bitfield``.
    """
    committee = get_crosslink_committee_for_attestation(
        state,
        attestation_data,
        committee_config,
    )

    return get_members_from_bitfield(committee, bitfield)