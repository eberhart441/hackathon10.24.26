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

- In scope (Must): two working room links with CSI streaming over USB serial; detection classifier with session-held-out evaluation; four-state dashboard served locally and offline; offline-node handling; persistent disclaimer; IDLE and ALARM_ACTIVE recording states; mode B RAM rolling buffer; recording indicator; UI-button alarm trigger; "End incident" action that returns to IDLE and purges the Incident_Record; RX heartbeats with offline detection within 10 seconds; health chip; test-mode toggle with banner and timeout; node-down test; simple inspection report.
- In scope (Should): fire mode with search-priority ranking; basic calibration mode running in CALIBRATION_State; node health panel; transmitter-dead vs receiver-dead distinction; hub-lost banner; responder tag firmware; RX tag summaries; hub room selection with hysteresis; crew marker; and the "responder present" label (Section 11d responder location).
- In scope (Could): "You are here" on a tag-bound second device joined to the laptop hotspot; calibrated per-room tag offsets; the "Mark searched?" suggestion when a tag dwells in a flagged room; nearest-room ordering within a search-priority tier; and a 24-hour maximum Incident_Record retention limit.
- Training data collection: raw CSI recording is performed only by the Training_Tool, a separate data-collection tool/build. The deployed Hub build contains no CSI write path.
- Out of scope (deferred / production): physical GPIO/dry-contact alarm trigger and buzzer; UDP transport for CSI records (UDP would require joining an access point and leaving the fixed sensing channel); body shape, pose, or identity estimation; fire-alarm-panel or life-safety-loop integration; cloud services, accounts, or remote access; regulatory certification (NFPA 72, UL); reliable people counting; breathing detection as a primary signal; full nine-check inspection checklist; mode A dormant capture; CLEARING hold; physical tablet deployment and laptop-to-tablet hotspot; sub-room responder position; location of untagged people; downed-responder detection; replacement for PASS devices or accountability systems.
- In scope (Should): edge-inference layer (Requirements 31–37), in which each RX_Node runs Edge_Features, the Edge_Model, and the room-state core on-device so detection and display keep working with the laptop unplugged. The Must remains the laptop Hub path (RX_Node streams raw CSI over serial in HUB_Mode; laptop Data_Pipeline plus CNN+GRU), which is also the fallback.
- Schedule gates: FEAT_Line and Room_State_Packet formats are frozen at 0:00–0:30. At the 5:30 feature freeze, if device and laptop outputs do not match (Parity_Check fails), the edge-inference layer is cut and RX_Nodes run HUB_Mode.
- Cut order (relative): Test_Mode is cut first, then the edge-inference layer, then the Responder_Tag.
- Out of scope / roadmap (edge): a temporal neural network on-device, deferred to ESP32-S3 (vector instructions, ESP-NN acceleration, optional PSRAM); authentication of Room_State_Packets beyond a MAC allow-list; encryption of ESP-NOW broadcasts.
- Hardware: the hackathon build increases to 5 ESP32 boards (2 TX, 2 RX, 1 Responder_Tag) with at most 1 spare. RX1 doubles as the Annunciator and carries Annunciator hardware (LEDs with series resistors, or an SSD1306-class I2C OLED). For the laptop-unplug demo, RX_Nodes are powered independently of the laptop (self-powered USB hub or power banks).

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
- **Heartbeat**: A once-per-second health message sent by each RX_Node to the Hub over serial, containing node identity, role, room, and the measured packet rate from its paired TX_Node (and additional fields in later tiers). TX_Nodes and the Responder_Tag have no serial link to the Hub and send no Heartbeats to the Hub.
- **Last_Evidence**: The most recent time a room produced occupancy evidence, where occupancy evidence means a smoothed moving probability of at least 80 percent or a smoothed still_present probability of at least 50 percent.
- **CALIBRATION_State**: A system state, entered from normal mode by an installer, in which calibration baselines and tag RSSI offsets are recorded and Tag_Summaries are processed; occupancy data is not persisted.
- **Training_Tool**: A separate data-collection tool/build, not a runtime state of the deployed Hub, that records raw CSI to disk; persistence of CSI exists only in the Training_Tool.
- **Searched_Mark**: A responder's explicit tap marking a room searched.
- **Health_Log**: The persisted log of node and component health events, kept across incidents and containing no occupancy data.
- **Occupancy_Data**: Room states, Confidence values, tag positions, and CSI.
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
- **RX_Mode**: The RX_Node operating mode, set in non-volatile config: HUB_Mode (streams raw CSI over serial to the Hub; the Must path and fallback), EDGE_Mode (computes features, classification, and room state on-device; streams no raw CSI), or TRAINING_Mode (streams raw CSI and FEAT_Lines together; used only with the Training_Tool).
- **HUB_Mode**: The RX_Mode in which the RX_Node streams raw CSI over serial to the Hub.
- **EDGE_Mode**: The RX_Mode in which the RX_Node computes Edge_Features, Edge_Model outputs, and room state on-device and streams no raw CSI.
- **TRAINING_Mode**: The RX_Mode in which the RX_Node streams raw CSI lines and FEAT_Lines together, used only with the Training_Tool.
- **Edge_Features**: The window features computed on the RX_Node: per-subcarrier variance, per-subcarrier change from the calibrated empty baseline, count of subcarriers over threshold, motion-band energy from one FFT on a signal combined across subcarriers, and 10-second and 30-second rolling statistics.
- **Edge_Model**: The on-device three-output classifier (empty, moving, still_present): either a tree-ensemble model exported to C (emlearn or m2cgen) or an INT8 TensorFlow Lite Micro dense network of about 5–20 KB with a 3-way softmax.
- **FEAT_Line**: The serial line carrying device-computed Edge_Features (and Edge_Model outputs when an Edge_Model is loaded) for one window.
- **Room_State_Packet**: The approximately 20-byte ESP-NOW broadcast (magic value "RSST") an RX_Node sends once per second containing room ID, sequence number, state, Confidence percentage, seconds since last motion, seconds since last presence, packet rate, calibrated flag, Edge_Model version, and the system alarm state with its incident identifier.
- **Annunciator**: A device that lights one LED or OLED row per room showing the four Room_States by blink pattern; RX1 doubles as the Annunciator in the 2-room demo, and a dedicated battery-backed board is used in deployment.
- **Parity_Check**: The acceptance test that compares Edge_Features and Edge_Model outputs from the device against the laptop's computation on the same recording.
- **Commissioned_RX**: An RX_Node whose MAC address is on the commissioned list.
- **Listener**: Any device that consumes Room_State_Packets, namely another RX_Node, the Annunciator, or the Hub via serial relay.
- **Hub_Neural_Network**: The CNN+GRU primary classifier of the Detection_Model that runs on the Hub.

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

1. THE TX_Node SHALL transmit ESP-NOW unicast packets to its paired RX_Node at a configurable fixed rate with a default between 50 and 100 packets per second, on a fixed channel selected from channels 1, 6, and 11, using an OFDM physical rate (HT MCS0) so that the RX_Node produces CSI.
2. WHEN an RX_Node captures a CSI packet, THE RX_Node SHALL filter by the paired TX_Node MAC address and discard packets from any other source.
3. WHEN an RX_Node forwards a CSI record, THE RX_Node SHALL include node identifier, TX MAC, sequence number, local timestamp, RSSI, channel, and per-subcarrier CSI amplitude in that record.
4. WHILE in HUB_Mode or TRAINING_Mode, THE RX_Node SHALL forward CSI records to the Hub over USB serial (UART) at a baud rate of at least 921600.
5. IF the configured packet rate and CSI record size exceed the serial link capacity, THEN THE RoomSense_System SHALL reduce load by lowering the packet rate to 50 packets per second or by forwarding only the L-LTF subcarriers, so that no CSI records are silently truncated.
6. WHILE in EDGE_Mode, THE RX_Node SHALL NOT forward raw CSI.

### Requirement 3: Node Configuration, Heartbeats, and Reboot Resilience

**User Story:** As an installer, I want nodes to be configurable and self-recovering, so that setup is fast and the system survives interruptions during a demo.

#### Acceptance Criteria

1. THE RX_Node SHALL send a Heartbeat to the Hub over serial once per second that includes the measured packet rate from its paired TX_Node, the CSI queue drop count, and the current RX_Mode.
2. THE Node SHALL allow its node identifier and room assignment to be configured without reflashing firmware.
3. WHEN a Node reboots, THE Node SHALL resume streaming without manual intervention.
4. WHEN a Node reboots, THE Node SHALL retain its configured node identifier and room assignment.
5. THE Hub SHALL infer TX_Node health from the paired RX_Node's measured packet rate, and THE Hub SHALL NOT expect Heartbeats from TX_Nodes or Responder_Tags.

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
6. WHEN training the neural network, THE RoomSense_System SHALL apply subcarrier dropout or subcarrier shuffle augmentation to reduce room-specific fingerprint learning.
7. WHEN the gradient-boosted-tree baseline outperforms the neural network on held-out-room evaluation, THE RoomSense_System SHALL ship the baseline as the live classifier.

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
3. WHEN the smoothed moving probability for a room is at least 80 percent, where smoothed means at least 2 of the most recent 3 feature windows or the average of the most recent 5 feature windows, THE State_Engine SHALL set that room to Motion detected and update that room's Last_Evidence.
4. WHEN the smoothed still_present probability for a room is at least 50 percent and the smoothed moving probability for that room is below 80 percent, THE State_Engine SHALL set that room to Possible presence and update that room's Last_Evidence.
5. WHEN at least 300 seconds have elapsed since a room's Last_Evidence, AND the Detection_Model reports empty with high confidence for that room, AND that room's link is healthy, where a healthy link means an RX Heartbeat has been received within 3 seconds, a fresh classified window has been produced within 5 seconds, and the measured packet rate is at or above the configured minimum, THE State_Engine SHALL set that room to No detection.
6. WHILE less than 300 seconds have elapsed since a room's Last_Evidence and no current evidence exists for that room and that room is not stale, THE State_Engine SHALL hold that room in Possible presence, and THE State_Engine SHALL NOT transition a room directly from Motion detected to No detection.
7. WHEN new occupancy evidence is produced for a room at any time, THE State_Engine SHALL reset that room's Last_Evidence to the time of that evidence, restarting the 300-second hold.
8. THE State_Engine SHALL record a Last_Seen timestamp for each room at 1-second resolution.
9. THE State_Engine SHALL assign each room a Confidence band of high meaning at least 80 percent, medium meaning 50 to 79 percent, or low meaning less than 50 percent, together with a numeric percentage from 0 to 100.
10. IF no RX Heartbeat has been received for a room's link within 10 seconds, OR no fresh classified window has been produced for that room within 5 seconds, OR the measured packet rate for that room's link is below the configured minimum, THEN THE State_Engine SHALL set that room to Unknown/offline and mark its displayed state as stale.
11. IF no RX Heartbeat has been received for a room's link within 3 seconds, THEN THE State_Engine SHALL mark that link degraded and set that room's Confidence to low.
12. THE State_Engine SHALL re-evaluate every room at least once per second independently of feature-window arrival, so that a room with no incoming windows cannot retain a stale state.
13. WHEN a window is flagged low quality for a room, THE State_Engine SHALL keep that room's current Room_State and set that room's Confidence to low.
14. THE State_Engine SHALL derive each room's Confidence from both the Detection_Model probability and the link quality, where link quality comprises the measured packet rate and Heartbeat freshness.
15. WHEN at least 300 seconds have elapsed since a room's Last_Evidence and the Detection_Model reports empty with high confidence on a healthy link for that room, THE State_Engine SHALL transition that room out of Possible presence to No detection.

### Requirement 9: Search-Priority Ranking

**User Story:** As a responder, I want rooms ranked so the most urgent appear first and unknown rooms are not dismissed, so that I search the right rooms first.

#### Acceptance Criteria

1. THE RoomSense_System SHALL rank rooms by Search_Priority in the strict order Motion detected first, Possible presence second, Unknown/offline third, and No detection fourth.
2. THE RoomSense_System SHALL rank every Unknown/offline room above every No detection room in all displayed orderings.
3. WHEN two rooms share the same Room_State, THE RoomSense_System SHALL break the tie deterministically by ranking the room with the more recent Last_Seen first.
4. WHEN a node meets the offline condition, defined as no heartbeat received within a 10-second window, THE RoomSense_System SHALL set its room to Unknown/offline and rank that room above No detection rooms within 10 seconds.
5. THE RoomSense_System SHALL rank every room with a Searched_Mark after every room without a Searched_Mark, preserving Search_Priority order within each group.

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

1. WHILE in IDLE_State, THE RoomSense_System SHALL persist no Occupancy_Data (room states, Confidence, tag positions, and CSI) and SHALL display the Recording_Indicator as "Not recording".
2. WHILE in IDLE_State, THE RoomSense_System SHALL maintain the mode B Rolling_Buffer in RAM only holding the most recent 120 seconds and SHALL NOT display, log, or transmit its contents.
3. WHEN an alarm is triggered, THE RoomSense_System SHALL enter ALARM_ACTIVE_State within 2 seconds, activate Fire_Mode, and display the Recording_Indicator as "Recording (alarm)".
4. WHEN an alarm is triggered, THE RoomSense_System SHALL freeze the Rolling_Buffer into the Incident_Record within 2 seconds.
5. WHILE in ALARM_ACTIVE_State, THE RoomSense_System SHALL persist only per-room state, Confidence, timestamps, node health events, and searched marks in the Incident_Record, and SHALL persist no other data.
6. THE Hub SHALL NOT persist raw CSI, identity, imagery, or audio, and raw CSI persistence SHALL exist only in the Training_Tool.
7. THE Dashboard SHALL keep the Recording_Indicator visible at all times.
8. WHILE in IDLE_State, THE RoomSense_System SHALL report a stored-samples counter value of exactly 0.
9. IF Occupancy_Data is written while in IDLE_State, THEN THE RoomSense_System SHALL raise a policy-violation fault, reject the write so that persisted storage is unchanged, and display a visible fault indication.
10. WHILE in IDLE_State, THE RoomSense_System SHALL allow writes of configuration, calibration baselines, and the Health_Log.
11. WHEN a responder taps "End incident" while in ALARM_ACTIVE_State, THE RoomSense_System SHALL return to IDLE_State and purge the Incident_Record according to the retention policy.
12. THE RoomSense_System SHALL support CALIBRATION_State, entered and exited from normal mode by an installer, in which THE RoomSense_System SHALL persist calibration baselines and tag RSSI offsets and SHALL NOT persist Occupancy_Data.

### Requirement 16: Demo Alarm Trigger

**User Story:** As a presenter, I want to trigger the alarm from a dashboard landing-page button, so that the hackathon demo enters fire mode without any physical hardware trigger.

#### Acceptance Criteria

1. THE Dashboard SHALL present an alarm-trigger button on a landing page.
2. WHILE in IDLE_State, WHEN the alarm-trigger button is activated, THE RoomSense_System SHALL transition to ALARM_ACTIVE_State within 2 seconds.
3. WHEN the alarm-trigger button is activated, THE Dashboard SHALL display a label identifying the trigger as simulated.
4. IF the alarm-trigger button is activated while already in ALARM_ACTIVE_State, THEN THE RoomSense_System SHALL keep ALARM_ACTIVE_State and take no additional transition.
5. THE RoomSense_System SHALL treat physical, GPIO, and dry-contact alarm triggers as out of scope for the hackathon demo.

### Requirement 17: Training Data Recording Mode

**User Story:** As an authorized installer, I want a separate training tool that records raw CSI to disk under access control, so that we can collect labeled data without compromising the deployed privacy posture.

#### Acceptance Criteria

1. THE Training_Tool SHALL record raw CSI to disk as a separate tool/build from the deployed Hub.
2. THE Training_Tool SHALL restrict recording to authorized installers only.
3. THE Training_Tool SHALL authorize exactly two team members to record training data.
4. WHEN recording a training session, THE Training_Tool SHALL label the data by one class per file.
5. THE Hub SHALL be built with no code path that writes raw CSI to disk.
6. WHEN recording a training session, THE Training_Tool SHALL record the FEAT_Lines received from the RX_Node together with the raw CSI.

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
7. WHERE transmitter-dead versus receiver-dead distinction is supported, IF a receiver is alive but the measured packet rate is below 20 percent for 5 seconds, THEN THE RoomSense_System SHALL report a transmitter-dead fault, and THE RoomSense_System SHALL use this packet-rate check as the sole TX_Node health signal.
8. WHERE hub-lost detection is supported, IF the hub becomes unreachable for 5 seconds, THEN THE Dashboard SHALL display a full-width hub-lost banner.
9. WHEN an RX Heartbeat is missing for 3 seconds, THE RoomSense_System SHALL mark that RX_Node degraded.
10. THE RoomSense_System SHALL write the Health_Log across incidents, including while in IDLE_State, and THE Health_Log SHALL contain no Occupancy_Data.

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
3. THE Hub SHALL retain raw CSI only within RAM rolling buffers, with disk persistence of raw CSI confined to the Training_Tool, and SHALL retain the state timeline for the current session only.
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
6. WHEN validating room generalization, THE RoomSense_System SHALL train on Room 1 data, evaluate on Room 2 data, and report the result.

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

1. WHEN an RX_Node receives an ESP-NOW broadcast, THE RX_Node SHALL accept the broadcast only if the broadcast carries the magic value "RSTG" and a commissioned tag ID, or carries the magic value "RSST" and originates from a Commissioned_RX MAC address, and SHALL discard every other broadcast.
2. THE RX_Node SHALL process Tag_Packets on a path separate from the CSI pipeline and SHALL exclude Tag_Packets from CSI processing.
3. WHEN an RX_Node reads a received Tag_Packet, THE RX_Node SHALL read the RSSI value from the ESP-NOW receive callback.
4. Once per second, for each tag heard during that second, THE RX_Node SHALL emit a Tag_Summary line over serial containing node_id, room_id, tag_id, packets_heard, mean_rssi, and max_rssi.
5. IF a tag was not heard during a given second, THEN THE RX_Node SHALL emit no Tag_Summary for that tag for that second.

### Requirement 25: Hub Tag Localization Logic [Should]

**User Story:** As an incident commander, I want the hub to estimate which room a tag is in with hysteresis and confidence, so that the located room is stable and honest.

#### Acceptance Criteria

1. THE Hub SHALL maintain a smoothed RSSI value per tag-and-room pair using an exponentially weighted moving average with a time constant of approximately 2 seconds, adjusted by a per-room offset learned during calibration.
2. THE Hub SHALL select as the candidate room the room with the highest adjusted smoothed RSSI for the tag, using a floor RSSI of -95 dBm for every room that did not hear the tag in the current interval.
3. WHEN the candidate room leads the current located room by at least 6 decibels continuously for at least 2 seconds, OR WHEN the current located room has not heard the tag for 3 seconds, THE Hub SHALL switch the Tag_Location to the candidate room.
4. THE Hub SHALL assign the Tag_Location a Confidence of high WHEN the leading room's lead over every other room, using the -95 dBm floor for silent rooms, is at least 10 decibels regardless of how many rooms hear the tag, a Confidence of medium WHEN that lead is between 6 and 10 decibels, and a Confidence of low otherwise or WHEN the leading room's link is degraded.
5. WHILE the Tag_Location Confidence is low, THE Dashboard SHALL display the location as "Near Room X / Room Y" and SHALL display no single room for that tag.
6. WHEN a tag is heard weakly by several rooms and no room meets the lead threshold, THE Dashboard SHALL display the Tag_Location as "Between rooms".
7. IF a tag has not been heard for 10 seconds, THEN THE Dashboard SHALL display a hollow Crew_Marker showing the last-heard room and the elapsed time, for example "Last heard Room 2, 0:40 ago", and SHALL NOT extrapolate the tag position.
8. WHEN the candidate room changes, THE Hub SHALL reset the 2-second lead timer.

### Requirement 26: Crew Marker and "You Are Here" Dashboard [Should for marker; Could for "You are here"]

**User Story:** As an incident commander and as a responder, I want to see crew positions on the floor plan, so that I know where crews are during an incident.

#### Acceptance Criteria

1. WHILE in Fire_Mode, THE Dashboard SHALL display a Crew_Marker in the tag's located room using a distinct icon and the tag-ID label, and SHALL NOT use a room-state color for the Crew_Marker.
2. THE Dashboard SHALL display the last-heard age of each Crew_Marker.
3. THE Dashboard SHALL display a per-floor count of crews on each floor tab.
4. WHERE a device is bound to a tag selected from a list in normal mode, THE Dashboard SHALL display "You are here" at the tag's Tag_Location and SHALL auto-switch to the tag's floor, where the tag-bound device is a second device (for example an iPhone) joined to the laptop's hotspot, preferably on 5 GHz to keep traffic off the sensing channel [Could].
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

1. WHILE in CALIBRATION_State, WHEN performing the room calibration walk-through while the installer wears the tag, THE Calibration_Mode SHALL record each room's tag RSSI to set a per-room offset.
2. WHILE in CALIBRATION_State, WHEN calibrating a room with the tag at that room's center, THE Calibration_Mode SHALL verify that the room hears the tag strongest.
3. WHILE in CALIBRATION_State, WHEN calibrating, THE Calibration_Mode SHALL record doorway RSSI values to tune the switching margin.
4. THE Calibration_Mode SHALL run tag calibration only in CALIBRATION_State.

### Requirement 29: Tag Privacy and Recording [Should]

**User Story:** As an occupant and as staff, I want tag locating limited to incidents, so that staff cannot be tracked day to day.

#### Acceptance Criteria

1. WHILE in ALARM_ACTIVE_State, Test_Mode, or CALIBRATION_State, THE RoomSense_System SHALL process Tag_Summaries.
2. WHILE in IDLE_State and not in CALIBRATION_State, THE RoomSense_System SHALL drop all Tag_Summaries.
3. THE RoomSense_System SHALL locate only commissioned tag IDs.
4. WHILE in ALARM_ACTIVE_State, THE RoomSense_System SHALL include tag positions in the Incident_Record under the existing retention rules, and THE RoomSense_System SHALL persist tag positions only in the Incident_Record.
5. WHILE in CALIBRATION_State, THE RoomSense_System SHALL persist only per-room tag RSSI offsets and SHALL NOT persist tag positions.

### Requirement 30: Tag Localization Failure Handling [Should]

**User Story:** As an incident commander, I want tag failures handled conservatively, so that a wrong room is never shown with false confidence.

#### Acceptance Criteria

1. WHEN any RX_Node is offline AND the leading adjusted smoothed RSSI for a tag is below -75 dBm, THE Hub SHALL force that tag's Tag_Location Confidence to low and THE Dashboard SHALL display "Near Room X / Room Y" rather than a single room.
2. WHEN a Responder_Tag loses power or crashes, THE Dashboard SHALL display a hollow Crew_Marker and THE Health_Chip SHALL raise a tag fault.
3. THE RoomSense_System SHALL treat the tag localization thresholds, including the 6-decibel lead, the 2-second lead duration, the 3-second silence window, the 10-second lost-tag window, the decibel Confidence bands, the -95 dBm silent-room floor, and the -75 dBm weak-signal threshold, as calibration-tunable starting values.

### Requirement 31: Edge Feature Extraction on the RX [Should]

**User Story:** As a developer, I want each RX_Node to compute window features from its own CSI, so that detection can run without streaming raw CSI to the Hub.

#### Acceptance Criteria

1. WHILE in EDGE_Mode or TRAINING_Mode, THE RX_Node SHALL compute Edge_Features for each window from the CSI of its own paired link.
2. WHEN the CSI receive callback accepts a CSI frame, THE RX_Node SHALL only copy that frame into a frame queue within the callback, and THE RX_Node SHALL run feature extraction and classification in a separate task pinned to core 1.
3. IF the frame queue is full when a CSI frame is accepted, THEN THE RX_Node SHALL drop that frame, increment the CSI queue drop count, and report the CSI queue drop count in its Heartbeat.
4. WHILE in EDGE_Mode or TRAINING_Mode, THE RX_Node SHALL complete feature extraction and classification for each window before the next window starts (calibration-tunable starting value).
5. WHEN computing motion-band energy for a window, THE RX_Node SHALL compute one FFT per window on a single signal combined across subcarriers.
6. THE RX_Node SHALL compute the 10-second and 30-second rolling statistics from per-window aggregates rather than from raw CSI frames.

### Requirement 32: Edge Classifier [Should]

**User Story:** As a developer, I want a compact on-device classifier, so that each RX_Node can classify occupancy without the Hub.

#### Acceptance Criteria

1. WHEN the Edge_Model receives Edge_Features for a window, THE Edge_Model SHALL output probabilities over exactly the three classes empty, moving, and still_present, where each probability is bounded between 0.0 and 1.0 inclusive and the three probabilities sum to 1.0 within a tolerance of 0.01.
2. THE RoomSense_System SHALL ship as the Edge_Model whichever of the C-exported tree-ensemble model or the INT8 TensorFlow Lite Micro dense network performs better on session-held-out evaluation, weighting recall on the moving and still_present classes first.
3. THE RoomSense_System SHALL run the Hub_Neural_Network only on the Hub and SHALL NOT deploy the Hub_Neural_Network to RX_Nodes.
4. WHEN an RX_Node sends a Room_State_Packet, THE RX_Node SHALL include the loaded Edge_Model version in that Room_State_Packet.

### Requirement 33: Training/Device Parity [Should]

**User Story:** As a developer, I want the device and laptop computations proven equivalent, so that a model trained on the laptop behaves the same on the RX_Node.

#### Acceptance Criteria

1. WHILE in TRAINING_Mode, THE RX_Node SHALL stream raw CSI lines and FEAT_Lines together over serial.
2. WHEN the RX_Node emits a FEAT_Line, THE RX_Node SHALL identify in that FEAT_Line the CSI frames the FEAT_Line was computed from by sequence range and frame count.
3. THE RoomSense_System SHALL train the Edge_Model on device-computed Edge_Features, taken either from recorded FEAT_Lines or regenerated from recorded raw CSI by the same feature-extraction source code compiled for the laptop.
4. WHEN an Edge_Model is flashed to an RX_Node for EDGE_Mode, THE RoomSense_System SHALL accept the Edge_Model only after the Parity_Check has passed on the same recording.
5. THE Parity_Check SHALL pass only WHEN Edge_Features agree within a configured tolerance, the argmax class agrees on at least 99 percent of windows, and per-class probabilities differ by at most 0.02 (calibration-tunable starting values).
6. IF the Parity_Check fails, THEN THE RX_Node SHALL remain in HUB_Mode.

### Requirement 34: Edge State Engine and Calibration Storage [Should]

**User Story:** As a responder, I want each RX_Node to hold an honest room state on its own, so that room state survives loss of the Hub.

#### Acceptance Criteria

1. WHILE in EDGE_Mode, THE RX_Node SHALL run the state-engine core for its room, comprising the Last_Evidence hold, seconds since last motion and seconds since last presence, low Confidence on poor link quality, and transmitter-dead detection from its measured packet rate, using the same thresholds as Requirements 8 and 19.
2. WHEN calibration completes for a room, THE RX_Node SHALL store that room's calibration baseline in non-volatile flash.
3. WHEN the RX_Node reboots, THE RX_Node SHALL load the stored calibration baseline from non-volatile flash.
4. IF no calibration baseline is stored, THEN THE RX_Node SHALL report its room as uncalibrated and Unknown/offline.
5. WHEN the RX state-engine core and the Hub State_Engine receive the same input sequence, THE RX state-engine core SHALL produce the same Room_State sequence as the Hub State_Engine.

### Requirement 35: Room-State Broadcast and Listeners [Should]

**User Story:** As a responder, I want room state broadcast between nodes, so that any Listener can show room state with the Hub disconnected.

#### Acceptance Criteria

1. WHILE in EDGE_Mode, THE RX_Node SHALL broadcast a Room_State_Packet once per second via ESP-NOW on the fixed sensing channel.
2. WHEN an RX_Node receives a Room_State_Packet, THE RX_Node SHALL exclude that Room_State_Packet from CSI processing by the paired TX_Node MAC address filter.
3. WHEN a Listener receives a Room_State_Packet, THE Listener SHALL accept that Room_State_Packet only if the Room_State_Packet originates from a Commissioned_RX MAC address.
4. IF a Listener has received no Room_State_Packet for a room for 3 seconds, THEN THE Listener SHALL show that room as Unknown/offline.
5. IF a Listener has received no Room_State_Packet for a room for 10 seconds, THEN THE Listener SHALL mark that room's RX_Node offline.
6. WHILE in IDLE_State, THE RX_Node SHALL withhold the occupancy fields (state, Confidence percentage, seconds since last motion, and seconds since last presence) from each over-the-air Room_State_Packet and SHALL carry only the health fields (packet rate, calibrated flag, Edge_Model version, and alarm state).
7. WHILE in IDLE_State and connected to the Hub over serial, THE RX_Node SHALL send full room state to the Hub over serial for use only by the RAM-only Rolling_Buffer, consistent with Requirement 15.2.
8. WHEN ALARM_ACTIVE_State is entered, THE RX_Node SHALL begin broadcasting full room state in each Room_State_Packet within 2 seconds.
9. WHEN an RX_Node receives an alarm command from the Hub over serial, or receives a Room_State_Packet from a Commissioned_RX carrying the alarm state for the current or a newer incident identifier, THE RX_Node SHALL latch the alarm state.
10. WHEN the RX_Node receives an End incident command, THE RX_Node SHALL apply the End incident command only if the command arrives directly from the Hub over serial, and SHALL discard any End incident indication received over the air.

### Requirement 36: Annunciator [Should]

**User Story:** As a responder, I want a simple per-room indicator that works without the laptop, so that I can still see room state if the Hub is lost.

#### Acceptance Criteria

1. THE Annunciator SHALL display one LED or OLED row per room showing the four Room_States, distinguishing each Room_State by blink pattern on LEDs or by icon and text on OLED in addition to any color.
2. IF the Annunciator has received no Room_State_Packet for a room for 3 seconds, THEN THE Annunciator SHALL show that room as Unknown/offline.
3. THE Annunciator SHALL display only the four valid Room_States Motion detected, Possible presence, No detection, and Unknown/offline, and SHALL NOT display "empty".
4. THE Annunciator SHALL show a self-alive indicator so that a dark display is distinguishable from every Room_State.
5. WHILE in IDLE_State, THE Annunciator SHALL show link health only and SHALL show no occupancy.
6. WHILE the Hub is disconnected, THE Annunciator SHALL continue displaying room state from received Room_State_Packets.

### Requirement 37: Laptop-Optional Operation and Deployed Privacy [Should]

**User Story:** As a responder and as an occupant, I want detection and display to survive loss of the laptop without exposing raw CSI, so that the system is resilient and private.

#### Acceptance Criteria

1. WHILE all RX_Nodes are in EDGE_Mode, THE RoomSense_System SHALL continue detection, room state, and Annunciator display with the Hub disconnected or the Hub process stopped, including during Fire_Mode.
2. WHILE the Hub is connected and the RX_Nodes are in EDGE_Mode, THE Hub SHALL provide the Dashboard, Crew_Markers, Incident_Record, and training, using Room_State_Packet data relayed over serial as the room-state source.
3. WHILE in EDGE_Mode, THE RX_Node SHALL transmit only derived room state and health data, and SHALL NOT transmit raw CSI over serial or over the air.
4. THE RX_Node SHALL transmit raw CSI over serial only in TRAINING_Mode or HUB_Mode, where HUB_Mode is the hackathon fallback and not the deployed configuration.
5. THE RoomSense_System SHALL present the claim "no single point of failure for detection and display" only for configurations in which both the Annunciator and the Hub Dashboard are available, SHALL NOT claim immunity to power loss, and SHALL state that every Node requires battery backup in deployment.
6. THE RoomSense_System SHALL document that in the 2-room demo RX1 is both a sensor and the Annunciator, and is therefore a shared point of failure for Room 1 and, with the laptop unplugged, for display.
7. WHEN the laptop is disconnected during the demo, THE RoomSense_System SHALL keep the RX_Nodes powered from a self-powered USB hub or power banks, or the demo SHALL stop the Hub process instead of removing power.
