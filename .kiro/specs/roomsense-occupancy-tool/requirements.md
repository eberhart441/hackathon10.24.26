# Requirements Document

## Introduction

RoomSense is a low-cost, offline-capable network of ESP32 WiFi-sensing nodes that estimates which rooms in a small building are likely occupied and presents first responders a prioritized, honest-confidence map when an alarm is triggered. The core question is "Is anyone likely still in this room, and how sure are we?" The system does not answer "what does the room look like" or "who is in it."

This requirements document scopes the 8-hour hackathon build. Requirements are written to satisfy the hackathon Must and Should priority tiers (Section 15 of the source spec and the per-section hackathon scope callouts), with production/long-term capabilities explicitly marked out of scope or deferred.

Three resolved decisions are incorporated throughout:
1. Exactly two team members are authorized to record training data.
2. No physical tablet is used at the hackathon. The dashboard is designed as a tablet-first responsive field view, but the hackathon demo runs on the team laptop screen with no tablet and no laptop-to-tablet hotspot link.
3. The hackathon demo alarm trigger is a UI button on a dashboard landing page. Physical/GPIO/dry-contact triggers remain part of the long-term design but are out of scope for the hackathon demo trigger.

Safety-critical behaviors emphasized across all requirements: the interface never displays "empty"; the Unknown/offline state ranks above the No detection state in search priority; confidence is reported honestly; the system operates fully offline after calibration; failures are always visible and never silently stale; and privacy is preserved with no imagery, audio, or identity captured and a RAM-only rolling buffer that persists only derived room state on alarm.

### Hackathon Scope Summary

- In scope (Must): two working room links with CSI streaming; detection classifier with session-held-out evaluation; four-state dashboard served locally and offline; offline-node handling; persistent disclaimer; IDLE and ALARM_ACTIVE recording states; mode B RAM rolling buffer; recording indicator; UI-button alarm trigger; heartbeats with offline detection within 10 seconds; health chip; test-mode toggle with banner and timeout; node-down test; simple inspection report.
- In scope (Should): fire mode with search-priority ranking; basic calibration mode; node health panel; transmitter-dead vs receiver-dead distinction; hub-lost banner; responder tag firmware; RX tag summaries; hub room selection with hysteresis; crew marker; and the "responder present" label (Section 11d responder location).
- In scope (Could): "You are here" on a tag-bound device; calibrated per-room tag offsets; the "Mark searched?" suggestion when a tag dwells in a flagged room; and nearest-room ordering within a search-priority tier.
- Out of scope (deferred / production): physical GPIO/dry-contact alarm trigger and buzzer; body shape, pose, or identity estimation; fire-alarm-panel or life-safety-loop integration; cloud services, accounts, or remote access; regulatory certification (NFPA 72, UL); reliable people counting; breathing detection as a primary signal; full nine-check inspection checklist; mode A dormant capture; CLEARING hold and 24-hour retention purge; physical tablet deployment and laptop-to-tablet hotspot; sub-room responder position; location of untagged people; downed-responder detection; replacement for PASS devices or accountability systems.
- Hardware: the hackathon build increases to 5 ESP32 boards (2 TX, 2 RX, 1 Responder_Tag) with at most 1 spare.

## Glossary

- **RoomSense_System**: The complete offline network of ESP32 sensing nodes, the hub pipeline, the detection model, the state engine, and the responder dashboard, considered as one system.
- **TX_Node**: An ESP32 node that transmits packets at a fixed rate on a fixed channel to a paired receiver.
- **RX_Node**: An ESP32 node that captures channel state information from its paired transmitter, timestamps records, and forwards them to the hub.
- **Node**: Any ESP32 device acting as a TX_Node or RX_Node.
- **CSI**: Channel State Information; per-subcarrier WiFi amplitude (and phase if available) measured by an RX_Node.
- **Hub**: The team laptop that hosts the data pipeline, classifier, state engine, and web server, receiving node data over USB serial without router dependency.
- **Data_Pipeline**: The hub software stages that ingest, validate, clean, window, and extract features from CSI records.
- **Detection_Model**: The classifier that assigns a window of features to one of the occupancy classes empty, moving, or still_present.
- **State_Engine**: The hub component that converts classifier outputs into exactly one displayed room state per room using hysteresis, last-seen tracking, and health.
- **Dashboard**: The locally served responsive web application that displays room states to responders and installers; designed tablet-first and run on the laptop screen for the hackathon.
- **Room_State**: Exactly one of Motion detected, Possible presence, No detection, or Unknown/offline displayed for a room.
- **Fire_Mode**: The responder view presenting a high-contrast, search-priority-ranked list of rooms with an alarm-time snapshot alongside the live view.
- **Calibration_Mode**: The installer workflow that records an empty baseline and reference activity to normalize a room and mark it calibrated.
- **Test_Mode**: An authorized, tagged, auto-expiring mode that exercises the system without a real alarm and produces an inspection report.
- **Heartbeat**: A once-per-second health message from a node containing node identity, role, room, and measured packet rate (and additional fields in later tiers).
- **Health_Chip**: A persistent dashboard header element summarizing sensor health (for example "All sensors online" or "2 faults").
- **Recording_Indicator**: A persistently visible dashboard element showing whether the system is recording (for example "Not recording" in IDLE, "Recording (alarm)" in ALARM_ACTIVE, "Recording (test)" in TEST).
- **Rolling_Buffer**: Mode B; a RAM-only two-minute ring buffer that is never displayed, logged, or sent until an alarm, at which point it is frozen into the incident record.
- **Incident_Record**: The persisted record created on alarm containing only derived per-room state, confidence, timestamps, node health events, and searched marks.
- **IDLE_State**: The system state where only heartbeats flow, nothing is persisted, and the Recording_Indicator reads "Not recording".
- **ALARM_ACTIVE_State**: The system state entered on alarm trigger where the Incident_Record is persisted and Fire_Mode is active.
- **Search_Priority**: The ordering of rooms for responder attention: 1 Motion detected, 2 Possible presence, 3 Unknown/offline, 4 No detection.
- **Last_Seen**: The timestamp of the most recent valid classification for a room.
- **Confidence**: A reported trust level for a Room_State expressed as a band (high, medium, low) plus a percentage.
- **Simulated_Data_Badge**: A dashboard indicator shown whenever displayed states derive from replayed or simulated data rather than live links.
- **Responder**: The primary user; a first responder who opens the Dashboard at an active alarm to decide where to search first.
- **Installer**: A user who sets up nodes, runs Calibration_Mode and Test_Mode, and is authorized to record training data.
- **Responder_Tag**: A fifth ESP32-WROOM-32E board worn by a responder that broadcasts ESP-NOW identification packets at 10 Hz on the fixed sensing channel; identified by a commissioned tag ID (for example "E1").
- **Tag_Packet**: The approximately 20-byte ESP-NOW broadcast emitted by a Responder_Tag containing the magic value "RSTG", the tag ID, a sequence number, and uptime in milliseconds.
- **Tag_Summary**: The once-per-second serial line an RX_Node emits for each tag heard, in the form TAG,<node_id>,<room_id>,<tag_id>,<packets_heard>,<mean_rssi>,<max_rssi>.
- **Crew_Marker**: The Dashboard marker, using a distinct icon plus a tag-ID label and never a room-state color, that shows a tagged responder's located room together with the last-heard age.
- **Tag_Location**: The Hub's estimate of which room a Responder_Tag is in, including the ambiguous values "Between rooms" and "Near Room X / Room Y", reported with a Confidence level.

## Requirements

### Requirement 1: Room-Level Occupancy Classification

**User Story:** As a responder, I want each room classified by occupancy activity, so that I can tell where someone is likely still present.

#### Acceptance Criteria

1. WHEN the Detection_Model receives a feature window for a room link, THE Detection_Model SHALL output class probabilities over exactly the three classes empty, moving, and still_present, where each probability is bounded between 0.0 and 1.0 inclusive and the three probabilities sum to 1.0 within a tolerance of 0.01.
2. THE Detection_Model SHALL output a smoothed occupied probability for each room computed as the sum of the moving probability and the still_present probability averaged over a sliding window of the most recent 5 feature windows, bounded between 0.0 and 1.0 inclusive.
3. WHEN classifying a feature window, THE Detection_Model SHALL complete inference within 50 milliseconds measured from feature-window receipt to probability output, per window per link.
4. THE RoomSense_System SHALL classify each room independently, such that a room's class probabilities are unchanged by other rooms' feature windows or classification results.
5. WHERE a room has not completed calibration, THE Dashboard SHALL mark that room as Unknown/offline and display an uncalibrated warning.
6. IF inference for a feature window exceeds the 50-millisecond limit, THEN THE RoomSense_System SHALL mark that room's result unavailable for that window and retain the last successful result.

### Requirement 2: Firmware CSI Capture and Transport

**User Story:** As an installer, I want nodes to capture and forward CSI reliably, so that the hub receives usable data from each room link.

#### Acceptance Criteria

1. THE TX_Node SHALL transmit packets at a configurable fixed rate with a default between 50 and 100 packets per second on a fixed channel selected from channels 1, 6, and 11.
2. WHEN an RX_Node captures a CSI packet, THE RX_Node SHALL filter by the paired TX_Node MAC address and discard packets from any other source.
3. WHEN an RX_Node forwards a CSI record, THE RX_Node SHALL include node identifier, TX MAC, sequence number, local timestamp, RSSI, channel, and per-subcarrier CSI amplitude in that record.
4. THE RX_Node SHALL forward CSI records over UART as the primary transport.
5. WHERE UART transport is unavailable, THE RX_Node SHALL forward CSI records over UDP as the secondary transport.

### Requirement 3: Node Configuration, Heartbeats, and Reboot Resilience

**User Story:** As an installer, I want nodes to be configurable and self-recovering, so that setup is fast and the system survives interruptions during a demo.

#### Acceptance Criteria

1. THE Node SHALL send a Heartbeat once per second that includes the measured packet rate.
2. THE Node SHALL allow its node identifier and room assignment to be configured without reflashing firmware.
3. WHEN a Node reboots, THE Node SHALL resume streaming without manual intervention.
4. WHEN a Node reboots, THE Node SHALL retain its configured node identifier and room assignment.

### Requirement 4: Data Pipeline Ingest and Validation

**User Story:** As a developer, I want incoming records validated and cleaned, so that the classifier receives consistent, quality-flagged data.

#### Acceptance Criteria

1. WHEN a CSI record is ingested, THE Data_Pipeline SHALL validate the TX MAC and sequence number.
2. IF a CSI record is malformed, THEN THE Data_Pipeline SHALL discard that record.
3. WHEN cleaning CSI records, THE Data_Pipeline SHALL drop null and guard subcarriers, resample to a fixed rate using the record timestamps, and apply a Hampel filter followed by a light moving average.
4. THE Data_Pipeline SHALL track the packet-loss rate per room link.
5. WHEN forming analysis windows, THE Data_Pipeline SHALL use windows of 1 to 2 seconds with 50 percent overlap.
6. IF a window exceeds the configured packet-loss threshold, THEN THE Data_Pipeline SHALL flag that window as low quality.

### Requirement 5: Feature Extraction

**User Story:** As a developer, I want informative features extracted from each window, so that the classifier can distinguish motion, stillness, and emptiness.

#### Acceptance Criteria

1. WHEN a window is formed, THE Data_Pipeline SHALL compute per-subcarrier and aggregated amplitude variance and standard deviation across time for that window.
2. WHEN a window is formed, THE Data_Pipeline SHALL compute mean amplitude and change relative to the calibrated empty baseline for that window.
3. WHEN a window is formed, THE Data_Pipeline SHALL compute spectral energy in the motion band of 0.5 to 5 hertz.
4. WHEN a window is formed, THE Data_Pipeline SHALL compute the count of subcarriers exceeding the baseline threshold.
5. THE Data_Pipeline SHALL compute rolling statistics over 10-second and 30-second horizons to support detection of a moving-then-still transition.
6. WHERE breathing-band energy between 0.2 and 0.4 hertz is computed, THE Data_Pipeline SHALL treat that feature as low-confidence supplementary input only.

### Requirement 6: Detection Model Training and Evaluation

**User Story:** As a developer, I want the model evaluated with held-out sessions and recall-prioritized metrics, so that the reported accuracy is honest and biased toward not missing people.

#### Acceptance Criteria

1. THE Detection_Model SHALL provide a small neural network as the primary classifier and a gradient-boosted-tree model on hand-crafted features as a baseline classifier.
2. WHEN evaluating the Detection_Model, THE RoomSense_System SHALL hold out entire recording sessions from the training set.
3. WHEN reporting evaluation results, THE RoomSense_System SHALL report a confusion matrix, per-class recall, and the false-"empty" rate.
4. WHEN selecting the primary evaluation metric, THE RoomSense_System SHALL prioritize recall on the moving and still_present classes.
5. THE Detection_Model SHALL bias its decision threshold toward the Possible presence outcome rather than the No detection outcome.

### Requirement 7: Calibration Mode

**User Story:** As an installer, I want to calibrate a room on site, so that classification adapts to the room and uncalibrated rooms are clearly flagged.

#### Acceptance Criteria

1. WHEN an installer starts calibration for a room, THE Calibration_Mode SHALL record a 30-second empty baseline followed by a walk-through and a 30-second still recording.
2. WHEN calibration recording completes for a room, THE Calibration_Mode SHALL fit baseline normalization for that room.
3. WHEN calibration completes for a room, THE RoomSense_System SHALL mark that room as calibrated with a timestamp.
4. WHILE a room is uncalibrated, THE Dashboard SHALL display a warning for that room.

### Requirement 8: Room State Model and Hysteresis

**User Story:** As a responder, I want each room to show exactly one honest state that cannot collapse abruptly, so that I trust the readout and am not misled by flicker.

#### Acceptance Criteria

1. THE State_Engine SHALL assign each room exactly one Room_State from the four valid states Motion detected, Possible presence, No detection, and Unknown/offline.
2. THE Dashboard SHALL NOT display "empty" as a room state, and THE Dashboard SHALL display only one of the four valid states Motion detected, Possible presence, No detection, and Unknown/offline.
3. WHEN the Detection_Model reports a moving probability in the high band of at least 80 percent for a room, THE State_Engine SHALL set that room to Motion detected.
4. WHEN the Detection_Model reports a still_present probability of at least 50 percent for a room, OR WHEN recent motion is followed by stillness within the configured 300-second lookback window, THE State_Engine SHALL set that room to Possible presence.
5. WHEN the Detection_Model reports empty with high confidence for a room whose link is healthy, where a healthy link means heartbeats have been received within a 10-second window, THE State_Engine SHALL set that room to No detection.
6. WHILE a room is in Motion detected, THE State_Engine SHALL require a minimum continuous hold of 300 seconds in Possible presence before the room may change to No detection, and THE State_Engine SHALL NOT transition a room directly from Motion detected to No detection.
7. IF motion or presence reappears during the 300-second hold, THEN THE State_Engine SHALL restart the hold timer.
8. THE State_Engine SHALL record a Last_Seen timestamp for each room at 1-second resolution.
9. THE State_Engine SHALL assign each room a Confidence band of high meaning at least 80 percent, medium meaning 50 to 79 percent, or low meaning less than 50 percent, together with a numeric percentage from 0 to 100.
10. WHEN a room link is degraded, where a degraded link means no heartbeat has been received within a 10-second window, THE State_Engine SHALL set that room to Unknown/offline and mark its displayed state as stale.

### Requirement 9: Search-Priority Ranking

**User Story:** As a responder, I want rooms ranked so the most urgent appear first and unknown rooms are not dismissed, so that I search the right rooms first.

#### Acceptance Criteria

1. THE RoomSense_System SHALL rank rooms by Search_Priority in the strict order Motion detected first, Possible presence second, Unknown/offline third, and No detection fourth.
2. THE RoomSense_System SHALL rank every Unknown/offline room above every No detection room in all displayed orderings.
3. WHEN two rooms share the same Room_State, THE RoomSense_System SHALL break the tie deterministically by ranking the room with the more recent Last_Seen first.
4. WHEN a node meets the offline condition, defined as no heartbeat received within a 10-second window, THE RoomSense_System SHALL set its room to Unknown/offline and rank that room above No detection rooms within 10 seconds.

### Requirement 10: Local Offline Dashboard

**User Story:** As a responder, I want the dashboard served locally and working offline, so that it functions at an incident with no internet or router.

#### Acceptance Criteria

1. THE Dashboard SHALL be served locally by the Hub and SHALL operate without internet or router connectivity.
2. THE Dashboard SHALL render on the laptop screen for the hackathon demo using a responsive tablet-first layout.
3. THE Dashboard SHALL display a persistent disclaimer banner stating that the readout is decision support and does not replace a full search.
4. THE Dashboard SHALL display a floor-plan view color-coded by Room_State with Confidence and Last_Seen shown per room.
5. WHILE displayed states derive from replayed or simulated data, THE Dashboard SHALL show the Simulated_Data_Badge.

### Requirement 11: Dashboard Normal Mode and Health Panel

**User Story:** As an installer, I want a normal-mode overview with node health and calibration controls, so that I can verify the system before an incident.

#### Acceptance Criteria

1. WHILE in normal mode, THE Dashboard SHALL display a status overview, a node health panel, and calibration controls.
2. THE Dashboard SHALL display a node health panel listing each node and its health status.
3. THE Dashboard SHALL maintain an event timeline held in memory for the current session only.
4. WHEN the current session ends, THE Dashboard SHALL discard the event timeline.

### Requirement 12: Accessibility and Grayscale-Distinguishable States

**User Story:** As a responder, I want every state distinguishable without relying on color and with large touch targets, so that the dashboard is usable under field conditions.

#### Acceptance Criteria

1. THE Dashboard SHALL distinguish every Room_State using an icon and label in addition to color, using the labels MOTION, POSSIBLE, UNKNOWN, and NO DETECTION.
2. THE Dashboard SHALL render every Room_State distinguishably in grayscale.
3. THE Dashboard SHALL render interactive touch targets at a minimum of 56 pixels.
4. THE Dashboard SHALL use high-contrast, outdoor-readable text and color treatments.

### Requirement 13: Tablet-First Floor-Plan Responder Workflow

**User Story:** As a responder, I want a floor plan where I can quickly find and work through the highest-priority rooms, so that I search efficiently during an alarm.

#### Acceptance Criteria

1. THE Dashboard SHALL display every room on the floor plan with color and icon indicating its Room_State.
2. WHILE in Fire_Mode, THE Dashboard SHALL display a side list containing only flagged rooms ordered by Search_Priority.
3. WHEN a responder enters Fire_Mode, THE Dashboard SHALL make the highest-priority room identifiable within 5 seconds.
4. WHEN a responder marks a room searched, THE Dashboard SHALL complete that action in at most 2 taps, dim the room, and move it to the bottom of the list.
5. WHEN a responder switches floors, THE Dashboard SHALL complete the switch in 1 tap and display an attention count per floor tab.
6. WHEN a responder selects a room, THE Dashboard SHALL present room details in a bottom sheet at most 2 taps away, including state, Confidence, last activity, alarm-time state, and link health.
7. WHEN all flagged rooms have been marked searched, THE Dashboard SHALL remind the responder that No detection rooms still require a sweep.
8. WHILE in Fire_Mode, THE Dashboard SHALL NOT require typing.

### Requirement 14: Fire Mode Snapshot and Degradation

**User Story:** As a responder, I want fire mode to freeze an alarm-time snapshot beside the live view and keep showing last-known state for failed nodes, so that I retain context as conditions change.

#### Acceptance Criteria

1. WHEN Fire_Mode is triggered, THE Dashboard SHALL switch to the responder view, freeze an alarm-time snapshot, and display the snapshot alongside the live view.
2. WHILE in Fire_Mode, THE Dashboard SHALL display rooms ranked by Search_Priority.
3. WHEN a node fails during Fire_Mode, THE Dashboard SHALL flip its room to Unknown/offline and display the last-known state with its age.
4. THE RoomSense_System SHALL NOT perform automatic dispatch or notification in the hackathon build.

### Requirement 15: Recording Policy, States, and Rolling Buffer

**User Story:** As an occupant and as a developer, I want the system to persist only derived room state and only after an alarm, so that privacy is preserved and recording status is always honest.

#### Acceptance Criteria

1. WHILE in IDLE_State, THE RoomSense_System SHALL persist no occupancy data and SHALL display the Recording_Indicator as "Not recording".
2. WHILE in IDLE_State, THE RoomSense_System SHALL maintain the mode B Rolling_Buffer in RAM only holding the most recent 120 seconds and SHALL NOT display, log, or transmit its contents.
3. WHEN an alarm is triggered, THE RoomSense_System SHALL enter ALARM_ACTIVE_State within 2 seconds, activate Fire_Mode, and display the Recording_Indicator as "Recording (alarm)".
4. WHEN an alarm is triggered, THE RoomSense_System SHALL freeze the Rolling_Buffer into the Incident_Record within 2 seconds.
5. WHILE in ALARM_ACTIVE_State, THE RoomSense_System SHALL persist only per-room state, Confidence, timestamps, node health events, and searched marks in the Incident_Record, and SHALL persist no other data.
6. WHERE the RoomSense_System is not in Training mode, THE RoomSense_System SHALL NOT persist raw CSI, identity, imagery, or audio.
7. THE Dashboard SHALL keep the Recording_Indicator visible at all times.
8. WHILE in IDLE_State, THE RoomSense_System SHALL report a stored-samples counter value of exactly 0.
9. IF occupancy data is written while in IDLE_State, THEN THE RoomSense_System SHALL raise a policy-violation fault, reject the write so that persisted storage is unchanged, and display a visible fault indication.

### Requirement 16: Demo Alarm Trigger

**User Story:** As a presenter, I want to trigger the alarm from a dashboard landing-page button, so that the hackathon demo enters fire mode without any physical hardware trigger.

#### Acceptance Criteria

1. THE Dashboard SHALL present an alarm-trigger button on a landing page.
2. WHILE in IDLE_State, WHEN the alarm-trigger button is activated, THE RoomSense_System SHALL transition to ALARM_ACTIVE_State within 2 seconds.
3. WHEN the alarm-trigger button is activated, THE Dashboard SHALL display a label identifying the trigger as simulated.
4. IF the alarm-trigger button is activated while already in ALARM_ACTIVE_State, THEN THE RoomSense_System SHALL keep ALARM_ACTIVE_State and take no additional transition.
5. THE RoomSense_System SHALL treat physical, GPIO, and dry-contact alarm triggers as out of scope for the hackathon demo.

### Requirement 17: Training Data Recording Mode

**User Story:** As an authorized installer, I want a training mode that records raw CSI to disk under access control, so that we can collect labeled data without compromising the deployed privacy posture.

#### Acceptance Criteria

1. WHERE Training mode is enabled, THE RoomSense_System SHALL record raw CSI to disk.
2. THE RoomSense_System SHALL restrict Training mode to authorized installers only.
3. THE RoomSense_System SHALL authorize exactly two team members to record training data.
4. WHEN recording a training session, THE RoomSense_System SHALL label the data by one class per file.

### Requirement 18: Test and Inspection Mode

**User Story:** As an installer, I want an authorized, auto-expiring test mode with a report, so that I can verify the system without triggering a real alarm.

#### Acceptance Criteria

1. WHEN an installer enters Test_Mode, THE RoomSense_System SHALL require an installer key switch or an authenticated PIN.
2. WHILE in Test_Mode, THE Dashboard SHALL display an amber TEST MODE banner and show the Recording_Indicator as "Recording (test)".
3. WHILE in Test_Mode, THE RoomSense_System SHALL auto-exit after 15 minutes and SHALL issue a warning 1 minute before auto-exit.
4. IF a real alarm is triggered while in Test_Mode, THEN THE RoomSense_System SHALL override Test_Mode and enter ALARM_ACTIVE_State.
5. THE RoomSense_System SHALL NOT make Test_Mode reachable from responder screens.
6. WHEN a node-down test is performed in Test_Mode, THE RoomSense_System SHALL set the affected room to Unknown/offline and raise a fault within 10 seconds.
7. WHEN Test_Mode ends, THE RoomSense_System SHALL produce a printable inspection report containing date and time, inspector, node list, health values, trigger result, and calibration dates, and SHALL exclude occupancy data from that report.

### Requirement 19: Self-Diagnostics and Health Reporting

**User Story:** As an installer and as a responder, I want continuous plain-language health reporting that is separate from occupancy data, so that I always know which sensors I can trust.

#### Acceptance Criteria

1. THE RoomSense_System SHALL report component health continuously even while not recording.
2. THE RoomSense_System SHALL keep health data separate from occupancy data, and Heartbeats SHALL contain no CSI or occupancy data.
3. WHEN a node heartbeat is missing for 10 seconds, THE RoomSense_System SHALL mark that node offline and display the fault in plain language within 10 seconds.
4. THE Dashboard SHALL display a Health_Chip in the header summarizing sensor health and SHALL open a fault list showing each cause and a suggested action when selected.
5. WHEN a node fault is active, THE Dashboard SHALL render the affected room as Unknown/offline with a fault indicator and rank that room above No detection rooms.
6. WHEN a previously offline node returns, THE RoomSense_System SHALL require 10 seconds of healthy heartbeats before removing the Unknown/offline state.
7. WHERE transmitter-dead versus receiver-dead distinction is supported, IF a receiver is alive but the measured packet rate is below 20 percent for 5 seconds, THEN THE RoomSense_System SHALL report a transmitter-dead fault.
8. WHERE hub-lost detection is supported, IF the hub becomes unreachable for 5 seconds, THEN THE Dashboard SHALL display a full-width hub-lost banner.

### Requirement 20: Reliability and Failure Handling

**User Story:** As a responder, I want failures and environmental changes handled conservatively, so that the system never silently presents stale or misleading data.

#### Acceptance Criteria

1. WHEN a node loses power and its heartbeat is missing beyond the offline threshold, THE RoomSense_System SHALL set its room to Unknown/offline.
2. IF the packet rate for a link collapses, THEN THE RoomSense_System SHALL set its room to Unknown/offline or reduce its Confidence.
3. WHEN the Hub restarts, THE RoomSense_System SHALL resume the pipeline from live data, reset the timeline, and set all rooms to Unknown/offline until fresh windows are available.
4. IF a router or channel change is detected, THEN THE RoomSense_System SHALL flag the change, apply a grace period, and SHALL NOT interpret the change as motion.
5. WHEN an environmental change is detected for a room, THE RoomSense_System SHALL raise a recalibration flag for that room.

### Requirement 21: Privacy, Ethics, and Safety

**User Story:** As an occupant, I want the system to capture no identifying information and to process everything locally, so that my privacy is protected.

#### Acceptance Criteria

1. THE RoomSense_System SHALL output per-room occupancy states only and SHALL NOT capture imagery, audio, or identity.
2. THE RoomSense_System SHALL process all data locally and SHALL NOT use cloud services, accounts, or remote access.
3. THE RoomSense_System SHALL retain raw CSI only within RAM rolling buffers except in Training mode, and SHALL retain the state timeline for the current session only.
4. THE Dashboard SHALL state through its disclaimer that the system is decision support and never replaces a full search.
5. WHEN raw training recordings are collected, THE RoomSense_System SHALL collect them only from consenting team members.

### Requirement 22: Test and Validation Plan

**User Story:** As a developer, I want a defined validation plan with honest reporting, so that demo claims are backed by measured, reproducible results.

#### Acceptance Criteria

1. WHEN validating detection, THE RoomSense_System SHALL evaluate empty versus occupied classification using session-held-out data and report actual moving and still_present recall.
2. WHEN validating the moving-to-still behavior, THE RoomSense_System SHALL verify that a moving-then-still sequence results in a Possible presence state.
3. WHEN validating person generalization, THE RoomSense_System SHALL train on two people and test on a third person.
4. WHEN validating node failure, THE RoomSense_System SHALL verify that a failed node results in an Unknown/offline room within the offline threshold.
5. WHEN reporting any validation result, THE RoomSense_System SHALL report the confusion matrix, the false-"empty" rate, and the test conditions.

### Requirement 23: Responder Tag Firmware (FW-8) [Should]

**User Story:** As an installer, I want a wearable tag that broadcasts its identity, so that room receivers can locate a responder.

#### Acceptance Criteria

1. THE Responder_Tag SHALL broadcast a Tag_Packet via ESP-NOW to the broadcast address FF:FF:FF:FF:FF:FF at a configurable default rate of 10 broadcasts per second.
2. WHEN sending each Tag_Packet, THE Responder_Tag SHALL apply random timing jitter bounded between -20 milliseconds and +20 milliseconds relative to the nominal 100-millisecond interval.
3. THE Responder_Tag SHALL operate in WiFi station mode on the same fixed channel used by the TX_Node and RX_Node sensing pairs.
4. THE Responder_Tag SHALL include in each Tag_Packet the magic value "RSTG", the commissioned tag ID, a sequence number, and the uptime in milliseconds, with a total payload of approximately 20 bytes.
5. WHEN the Responder_Tag sends a Tag_Packet, THE Responder_Tag SHALL blink its onboard LED so the wearer can confirm the tag is operating.
6. THE Responder_Tag SHALL enable the task watchdog so that a hung tag reboots automatically.

### Requirement 24: RX Tag Reception and Summaries (FW-9) [Should]

**User Story:** As a developer, I want RX nodes to report tags separately from CSI, so that localization works without polluting occupancy sensing.

#### Acceptance Criteria

1. WHEN an RX_Node receives an ESP-NOW broadcast, THE RX_Node SHALL accept the broadcast only if the broadcast carries the magic value "RSTG" and a commissioned tag ID, and SHALL discard every other broadcast.
2. THE RX_Node SHALL process Tag_Packets on a path separate from the CSI pipeline and SHALL exclude Tag_Packets from CSI processing.
3. WHEN an RX_Node reads a received Tag_Packet, THE RX_Node SHALL read the RSSI value from the ESP-NOW receive callback.
4. Once per second, for each tag heard during that second, THE RX_Node SHALL emit a Tag_Summary line over serial containing node_id, room_id, tag_id, packets_heard, mean_rssi, and max_rssi.
5. IF a tag was not heard during a given second, THEN THE RX_Node SHALL emit no Tag_Summary for that tag for that second.

### Requirement 25: Hub Tag Localization Logic [Should]

**User Story:** As an incident commander, I want the hub to estimate which room a tag is in with hysteresis and confidence, so that the located room is stable and honest.

#### Acceptance Criteria

1. THE Hub SHALL maintain a smoothed RSSI value per tag-and-room pair using an exponentially weighted moving average with a time constant of approximately 2 seconds, adjusted by a per-room offset learned during calibration.
2. THE Hub SHALL select as the candidate room the room with the highest adjusted smoothed RSSI for the tag.
3. THE Hub SHALL switch the Tag_Location to the candidate room IF the candidate room leads the current room by at least 6 decibels for at least 2 seconds, OR IF the current room has not heard the tag for 3 seconds.
4. THE Hub SHALL assign the Tag_Location a Confidence of high WHEN the lead is at least 10 decibels and at least 2 rooms hear the tag, a Confidence of medium WHEN the lead is between 6 and 10 decibels, and a Confidence of low otherwise or WHEN the leading room's link is degraded.
5. WHILE the Tag_Location Confidence is low, THE Dashboard SHALL display the location as "Near Room X / Room Y" and SHALL display no single room for that tag.
6. WHEN a tag is heard weakly by several rooms and no room meets the lead threshold, THE Dashboard SHALL display the Tag_Location as "Between rooms".
7. IF a tag has not been heard for 10 seconds, THEN THE Dashboard SHALL display a hollow Crew_Marker showing the last-heard room and the elapsed time, for example "Last heard Room 2, 0:40 ago", and SHALL NOT extrapolate the tag position.

### Requirement 26: Crew Marker and "You Are Here" Dashboard [Should for marker; Could for "You are here"]

**User Story:** As an incident commander and as a responder, I want to see crew positions on the floor plan, so that I know where crews are during an incident.

#### Acceptance Criteria

1. WHILE in Fire_Mode, THE Dashboard SHALL display a Crew_Marker in the tag's located room using a distinct icon and the tag-ID label, and SHALL NOT use a room-state color for the Crew_Marker.
2. THE Dashboard SHALL display the last-heard age of each Crew_Marker.
3. THE Dashboard SHALL display a per-floor count of crews on each floor tab.
4. WHERE a device is bound to a tag selected from a list in normal mode, THE Dashboard SHALL display "You are here" at the tag's Tag_Location and SHALL auto-switch to the tag's floor.
5. WHILE in Fire_Mode, THE Dashboard SHALL NOT require typing to bind a device to a tag.
6. IF a tag is silent for 10 seconds during an incident, THEN THE Health_Chip SHALL show a fault identifying the tag and its last-heard room, for example "E1 tag not heard. Last heard Room 2.".

### Requirement 27: Interaction with Occupancy States [Should for labels]

**User Story:** As a responder, I want responder presence annotated without hiding occupancy, so that a responder in a room never masks a possible occupant.

#### Acceptance Criteria

1. WHILE a tag is located in a room at medium or high Confidence, THE Dashboard SHALL label Motion in that room as "Motion . responder present".
2. THE RoomSense_System SHALL NOT downgrade or hide a Motion detected state because a Responder_Tag is present.
3. WHEN a responder leaves a room that holds Possible presence, THE Dashboard SHALL annotate that room with "recent motion may be responder" without changing the Room_State or the Search_Priority.
4. THE alarm-time snapshot SHALL remain unaffected by tag presence.
5. IF a tag remains in a flagged room for at least 20 seconds, THEN THE Dashboard SHALL offer a "Mark searched?" suggestion in that room's detail sheet, for example "E1 was here 0:45 . Mark searched?".
6. THE RoomSense_System SHALL NOT mark any room searched automatically, and marking a room searched SHALL require a responder tap.

### Requirement 28: Tag Calibration and Per-Room Offsets [Could]

**User Story:** As an installer, I want to calibrate tag reception per room, so that localization offsets and margins are tuned.

#### Acceptance Criteria

1. WHEN performing the room calibration walk-through while the installer wears the tag, THE Calibration_Mode SHALL record each room's tag RSSI to set a per-room offset.
2. WHEN calibrating a room with the tag at that room's center, THE Calibration_Mode SHALL verify that the room hears the tag strongest.
3. WHEN calibrating, THE Calibration_Mode SHALL record doorway RSSI values to tune the switching margin.

### Requirement 29: Tag Privacy and Recording [Should]

**User Story:** As an occupant and as staff, I want tag locating limited to incidents, so that staff cannot be tracked day to day.

#### Acceptance Criteria

1. THE RoomSense_System SHALL process Tag_Summaries only WHILE in ALARM_ACTIVE_State or Test_Mode.
2. WHILE in IDLE_State, THE RoomSense_System SHALL drop all Tag_Summaries.
3. THE RoomSense_System SHALL locate only commissioned tag IDs.
4. WHILE in ALARM_ACTIVE_State, THE RoomSense_System SHALL include tag positions in the Incident_Record under the existing retention rules.

### Requirement 30: Tag Localization Failure Handling [Should]

**User Story:** As an incident commander, I want tag failures handled conservatively, so that a wrong room is never shown with false confidence.

#### Acceptance Criteria

1. WHEN the RX_Node in a tag's actual room is offline, THE Hub SHALL force the Tag_Location Confidence to low and SHALL display "Near Room X / Room Y" rather than a single room.
2. WHEN a Responder_Tag loses power or crashes, THE Dashboard SHALL display a hollow Crew_Marker and THE Health_Chip SHALL raise a tag fault.
3. THE RoomSense_System SHALL treat the tag localization thresholds, including the 6-decibel lead, the 2-second lead duration, the 3-second silence window, the 10-second lost-tag window, and the decibel Confidence bands, as calibration-tunable starting values.
