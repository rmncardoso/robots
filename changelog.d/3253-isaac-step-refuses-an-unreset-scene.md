
**A failed `add_object` marks the scene stale too.** Only the success path set the
flag, and the failure path is stale by the same mechanism - which that handler's own
comment already states: `_construct_shape_prim` stops the timeline, clearing the
physics sim view, *before* constructing a dynamic prim. By the time the handler runs
the view is already invalid whether the construction went on to succeed or to raise.

So a failed `add_object` left `step()` willing to advance, and the clock moved over a
scene PhysX was no longer simulating while every robot's `get_observation` came back
empty - the exact degradation the flag was added to refuse. To a caller it read as a
transient add failure followed by a sim that had quietly stopped simulating: no
exception, a plausible error envelope, and then empty observations attributed to
whatever ran next.

Pinned across all six exception types the handler names, and by a drift guard that
derives from the source: any `return` below the `_construct_shape_prim` call which
does not have the flag set on the way is a new instance of this bug. There were two
such returns when only one was covered.
