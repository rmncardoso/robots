### Added: a DDS domain for the Unitree drivers, held to the shared domain rule

`ChannelFactoryInitialize(domain_id, network_interface)` takes a domain beside
the interface, and `ensure_dds` passed the literal `0`. So the G1 and Go2
drivers, both halves of the DDS engine and `use_unitree` could only ever reach
a bus on domain 0: a simulator, or a bench rig deliberately kept off the
robots' domain, had no keyword to name it - while the sibling native driver for
the Booster T1 has taken `domain_id=` since it landed.

All five surfaces now take `domain_id`, defaulting to `0` - the domain the
robot ships on, and the one the vendor's examples pass - so a caller that names
nothing binds exactly what it bound before:

```python
Robot("g1", mode="real", driver="strands", port="192.168.123.161",
      network_interface="eth0", domain_id=7)
```

`get_status()` reports the domain beside the interface, as the Booster driver's
does, so a caller can read back what the bus will bind before a frame is
written.

The dashboard's spawn request takes `domain_id` the way it takes
`network_interface` (the Devices form does not offer the field yet).
The registry's `real_transport` says which drivers declare it (the Unitree
drivers and the Booster T1); naming one for any other driver, or naming a value
that is not a domain, is refused before a process exists; and the spawner hands
it to `Robot`, so a spawn that names none still builds its driver on domain 0.
A camera change, which respawns the robot, hands it both again: it used to
bring a networked robot back on its driver's default interface.

The value is refused through the *shared* domain rule
(`strands_robots.utils.dds_domain_id_error`) rather than a local test, for the
reason the telemetry bridges and the Booster driver use it: a domain id indexes
the RTPS port map, so it has a ceiling (`MAX_DDS_DOMAIN_ID`, whose discovery
ports are the last that fit the 16-bit port space) as well as a floor, and
`True`, `2.7` and `"5"` are not ids an `int()` coercion should quietly turn into
domains 1, 2 and 5. An id this bus accepted and the bridges advertising the same
robot's topics refused would be a robot publishing where nothing subscribes. The
guard runs ahead of `ensure_dds`'s lazy SDK import, so an unusable value reports
the same with the vendor SDK installed and without it, and
`tests/test_dds_domain_id_domain.py` now grades both drivers over the same
fourteen unusable and five usable values as every other domain surface.
`use_unitree` refuses one in the same words before its operator-approval gate,
so an operator is never asked to approve a command that could only fail on its
domain.

A second, *different* domain in one process is refused the way a second
interface already is, and for the same reason: `ChannelFactory.Init`
short-circuits on `if __initialized: return True`, so the later domain never
reaches the SDK and the endpoints built after it would sit on the first domain,
reading topics nobody publishes there.

```
ensure_dds("eth0", 7)  ->  None
ensure_dds("eth0", 9)  ->  "ChannelFactoryInitialize was called with domain 7;
                            refusing to re-initialise on domain 9"
```

So a verb that omits the keyword on a bus already bound to another domain is
told which domain is up, rather than attaching its endpoints to one nobody
chose for it.

The twelve test doubles, in nine test files, that stood in for `ensure_dds` with
a one-parameter lambda take the second parameter too, so each still carries the
signature of the function it replaces.
