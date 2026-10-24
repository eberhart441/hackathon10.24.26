# Glossary

Shared vocabulary for this project. Definitions only; implementation details live elsewhere.

**Node**: any one ESP32 board in the sensing network.

**Master**: the single node that broadcasts the radio signal on a steady schedule. Also called the transmitter. Avoid: sender.

**Slave**: a node that listens to the master's broadcasts, measures how the signal changed, and reports the measurement to the laptop. Also called a receiver.

**Link**: one master-to-slave pair. The link is the unit that is sensed; each link has its own motion verdict. The demo has two links.

**Doorway link**: the link whose path someone must cross to enter or leave the room. It works as a tripwire.

**Interior link**: the link whose path covers the open floor of the room.

**Zone**: the part of a room that a link is responsible for (for example the doorway area or the interior). Position in this project means zone or room state, never coordinates.

**CSI (Channel State Information)**: a measurement of how the radio signal changed on its way from the master to a slave, reported per frequency component (subcarrier). The raw input to everything else.

**Motion / No motion**: the verdict for one link over a short window of time. The only thing the model outputs.

**Incident**: the period from the fire alarm triggering until the incident is closed. Trails and logs are kept only while an incident is open.

**Flag**: a room marked "search first" because someone was seen moving in it, motion stopped, and no exit was detected afterwards.

**Search priority**: the ranked list of flagged rooms shown to firefighters. Never "clear" or "empty".

**Motion last seen**: how long ago motion was last detected in a room. Shown instead of any claim that a room is empty.

**Gateway** (retired for the demo): an earlier idea of a separate node that forwarded data to a Raspberry Pi. In the demo the slaves connect straight to the laptop.

## RoomSense spec names

The teammates' requirements spec (`.kiro/specs/roomsense-occupancy-tool/requirements.md`) uses different names for the same things. Both are fine; this is the mapping.

| This glossary | RoomSense spec |
|---------------|----------------|
| Master | TX_Node |
| Slave | RX_Node |
| Node | Node |
| Link | a TX_Node paired with an RX_Node (a "room link") |
| Tag | Responder_Tag |
| Hub | the team laptop that runs the pipeline, model, state engine and dashboard |
