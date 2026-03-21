# Outdoor Autonomous Rover Design Review

Date: 2026-03-21

Scope:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md`
- `docs/plans/2026-03-21-outdoor-autonomous-driving-implementation.md`
- `docs/plans/2026-03-21-outdoor-wiring-guide.md`

## Findings

### 1. Critical: the REST migration regresses `scan`, and the obstacle-avoidance story is not actually implemented

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md` lines 136-140, 184-186
- `docs/plans/2026-03-21-outdoor-autonomous-driving-implementation.md` lines 589-592, 954-958, 1090-1102

Problem:
- The design says navigation should stop, scan, pick the clearest direction, and resume around obstacles.
- Task 4 implements `POST /command` with `action == "scan"` by returning a plain `STATUS` response, not a 360-degree scan.
- Task 6 then stops on obstacles and explicitly defers scan logic to "the future".
- Task 7 says to move all existing tools to REST, which would also downgrade the current `rover_scan` behavior on the Pi5 path.

Why it matters:
- This is the biggest behavior mismatch in the whole set of docs.
- On paper, v1 sounds like it can navigate around simple obstacles. In the implementation plan, it cannot.
- It also risks breaking an existing operator tool during the SSH -> REST migration.

Recommendation:
- Either reduce the v1 design to "stop on obstacle and wait for operator input", or add a real `scan` endpoint and test it before migrating the Pi5 tools.

### 2. Critical: `roverd` is exposed on `0.0.0.0` with no authentication or authorization

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md` lines 92-98
- `docs/plans/2026-03-21-outdoor-autonomous-driving-implementation.md` lines 651-679

Problem:
- The daemon exposes motor and navigation endpoints on all interfaces by default.
- There is no shared secret, auth token, IP allowlist, or reverse-proxy protection in the design or plan.

Why it matters:
- On a phone hotspot or any shared WiFi, another client that can reach the Pi can send `/command`, `/navigate`, or `/stop`.
- That is a safety issue, not just a security nicety.

Recommendation:
- For v1, bind to a specific interface or localhost plus SSH tunnel, or require a simple bearer token header on every mutating endpoint.

### 3. High: the wiring guide can damage some compass modules by treating the HMC5883L as a 5V device

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md` lines 63-70
- `docs/plans/2026-03-21-outdoor-wiring-guide.md` lines 30-36, 43-49, 55-57

Problem:
- The guide puts the HMC5883L on the 5V rail.
- That is only safe for breakout boards with onboard regulation and level shifting.
- The docs do not specify the exact breakout variant, so the wiring guide reads as if 5V is always correct.

Why it matters:
- On 3.3V-only breakouts, this can permanently damage the compass.
- Even on "5V-friendly" boards, the doc should say that explicitly because this is the one place a user is most likely to wire by rote.

Recommendation:
- Name the exact compass module variant.
- If the board is not explicitly 5V-tolerant, power it from 3.3V and confirm I2C pull-up voltage before power-on.

### 4. High: `LM7805 or buck converter` is too loose; the LM7805 is a poor default for both 4xAA and LiPo

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md` line 30
- `docs/plans/2026-03-21-outdoor-wiring-guide.md` lines 9-10, 24-28

Problem:
- The docs present an LM7805 and a buck converter as equivalent choices.
- They are not equivalent here:
  - 4xAA gives marginal headroom for a 7805 once cells sag under load.
  - A LiPo feeding a 7805 wastes power as heat.

Why it matters:
- Outdoor driving plus WiFi plus GPS is exactly the kind of load that will expose regulator dropout and brownout problems.
- This is more likely to cause random resets than almost any other hardware choice in the design.

Recommendation:
- Make a switching buck regulator the v1 default.
- Remove the LM7805 from the main recommendation unless input voltage, load current, and thermal budget are fully spelled out.

### 5. High: the GPS parser and navigation loop do not detect stale position data

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md` lines 115-118, 130-131
- `docs/plans/2026-03-21-outdoor-autonomous-driving-implementation.md` lines 179-203, 775-791, 928-930

Problem:
- The design says "no fix = stop and wait".
- The implementation only tracks `has_fix`, `lat`, `lng`, and `speed_knots`; it never stores the timestamp of the last valid fix.
- If the GPS reader stalls after one valid sentence, navigation can keep using the last coordinates forever.

Why it matters:
- A stale fix is functionally equivalent to blind driving.
- This is especially risky because the navigation loop is only 1 Hz, so it will happily keep issuing commands based on old data.

Recommendation:
- Add `last_fix_time` and fail closed if no fresh valid fix has arrived within a short timeout, for example 2-3 seconds.

### 6. High: the GPS parser is too narrow for real NEO-6M output

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md` lines 115-117
- `docs/plans/2026-03-21-outdoor-autonomous-driving-implementation.md` lines 186-189

Problem:
- The parser only accepts sentences starting with `$GPRMC`.
- Real u-blox modules commonly emit `$GNRMC` depending on configuration and constellation mode.

Why it matters:
- This can produce a system that "works in tests" and never gets a usable fix on actual hardware.

Recommendation:
- Parse any `RMC` talker ID, not just `GP`.
- Add tests for both `$GPRMC` and `$GNRMC`.

### 7. High: repeated `/navigate` calls can create multiple navigation loops, and the task lifecycle is underspecified

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-implementation.md` lines 542, 622-649, 982-991

Problem:
- `nav_task` exists but the plan never cancels it on `/stop` or `/pause`.
- `handle_navigate` starts a new async loop every time it is called.
- There is no guard against starting navigation twice.

Why it matters:
- Two loops issuing motor commands concurrently is a real control-path hazard.
- Even if the `mode` flag eventually stops one loop, this is still a race in the most safety-sensitive part of the system.

Recommendation:
- Treat navigation as a single owned task.
- Reject a new `/navigate` while one is active, or cancel and await the old task before starting another.

### 8. Medium: the documented `/status` contract does not match the planned implementation

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md` lines 157-163
- `docs/plans/2026-03-21-outdoor-autonomous-driving-implementation.md` lines 601-620

Problem:
- The design says `nav` should include `distance_to_wp` and `bearing`.
- The implementation only returns waypoint index and total count.
- It also returns `waypoint` as a zero-based index, while the design examples read like one-based operator-facing numbering.

Why it matters:
- This will leak straight into OpenClaw behavior and user-facing status reports.
- It is an API contract mismatch between the design doc and the implementation plan.

Recommendation:
- Decide the final JSON shape now and keep the design and implementation plan aligned.

### 9. Medium: the compass plan is optimistic about heading quality near motors and on uneven ground

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md` lines 120-139
- `docs/plans/2026-03-21-outdoor-autonomous-driving-implementation.md` lines 1298-1316
- `docs/plans/2026-03-21-outdoor-wiring-guide.md` lines 245-246

Problem:
- The design treats the compass as an absolute heading source for waypoint steering.
- The implementation is raw `atan2(y, x)` with no hard-iron calibration, soft-iron calibration, magnetic declination, or tilt compensation.

Why it matters:
- On a small chassis with motors, battery leads, and a steel fastener or two nearby, the error can be large enough to overwhelm the 5 degree and 15 degree steering thresholds.
- This is likely to be the main practical reason the rover zig-zags or never converges cleanly to a waypoint.

Recommendation:
- Simplify v1 expectations: use the compass only for coarse heading, mount it far from motors, and add at least basic calibration plus a field procedure.

### 10. Medium: a 5 meter arrival threshold is aggressive for a low-cost GPS-only v1

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-design.md` lines 132-149

Problem:
- The design uses `< 5m` as the waypoint-arrival condition with no hysteresis, no dwell requirement, and no "consecutive fixes" rule.

Why it matters:
- Consumer GPS error in real outdoor conditions often lands in the same range as the arrival threshold.
- That makes false arrival, oscillation around a waypoint, and skipped waypoints much more likely than the doc implies.

Recommendation:
- For v1, use a looser threshold such as 8-10m, or require multiple consecutive in-radius fixes before advancing.

### 11. Medium: the wiring guide's I2C troubleshooting points at the wrong bus

Refs:
- `docs/plans/2026-03-21-outdoor-wiring-guide.md` lines 106-124, 247-248

Problem:
- The guide correctly shows the gyro and compass on the Arduino I2C bus.
- The troubleshooting section then suggests `i2cdetect -y 1` on the Pi Zero for those same devices.

Why it matters:
- That check will not validate the architecture shown in the document.
- It sends the reader to the wrong debugging tool and can waste time during bring-up.

Recommendation:
- Replace the Pi `i2cdetect` advice with an Arduino-side I2C scanner sketch, or explicitly say the Pi command only applies if the sensors are later moved to the Pi bus.

### 12. Medium: the implementation plan under-tests the most failure-prone paths

Refs:
- `docs/plans/2026-03-21-outdoor-autonomous-driving-implementation.md` lines 723-803, 823-1003, 1158-1164, 1236-1243

Problem:
- The plan has unit coverage for math and parsing, but it does not add tests for:
  - invalid waypoint payloads
  - repeated `/navigate`
  - `/stop` while navigating
  - GPS timeout/stale-fix behavior
  - REST-mode plugin compatibility
  - `rover-remote navigate` malformed JSON handling
- Tasks 7 and 8 rely only on manual testing despite changing the primary control path.

Why it matters:
- These are the exact edges most likely to fail in field use.
- The plan is strongest on low-risk pure-Python pieces and weakest on the operator and safety path.

Recommendation:
- Add one integration test layer around `roverd` state transitions and one small test pass for the Pi5 REST clients before field testing.

## Simplifications Worth Considering

1. Make v1 explicitly "GPS waypoint drive in open space, stop on obstacle, operator decides next move."
2. Use a buck converter only; do not present the LM7805 as an equal option.
3. Keep scan on the current serial path until a real server-side scan API exists.
4. Loosen waypoint arrival logic and heading expectations for the first outdoor field tests.
5. Treat compass bring-up as an experiment, not as a guaranteed absolute-heading source.

## Most Important Fixes Before Hardware Bring-Up

1. Clarify compass power voltage and exact module part number.
2. Remove or constrain the unauthenticated `0.0.0.0` REST exposure.
3. Decide whether v1 actually avoids obstacles or just stops for help.
4. Add stale-GPS detection and broaden NMEA parsing.
5. Replace the LM7805 recommendation with a buck converter.
