# Plan: validation sets and cross-validation for the CSI motion model

Goal: get an honest accuracy estimate for the CSI motion classifier without a pre-existing validation set.

Scope: the model classifies **room-level motion state** only. It does not identify people or objects, and it does not detect still bodies or breathing. Never label a room "empty" or "clear"; use `no_motion_seen`.

Input format: see `firmware/docs/serial-protocol.md` (CSI records, 64 amplitudes, about 100 packets/s).

## 1. Model classes vs room states

Two layers. Only the first is trained and labelled in recordings.

### Model classes (ML, labelled per recording)

| Label | Meaning |
|-------|---------|
| `no_motion_seen` | Room with nobody moving (not a claim that it is empty) |
| `motion` | A person walking or moving in the room |
| `doorway_crossing` | A person passes through the doorway (optional; only used if reliable) |

### Room states (pure-function state machine on top of the model, not ML)

| State (display) | Rule |
|-----------------|------|
| MOTION NOW (was OCCUPIED) | Model reports `motion` within the last ~5 s. Motion detected, not a confirmed person |
| MOTION LAST SEEN (was LIKELY OCCUPIED) | Earlier motion, no doorway exit seen. Shows age |
| UNVERIFIED | No data, node offline (no heartbeat for 10 s), or low model confidence. Default state |
| RESPONDER-MARKED (was CLEARED) | Set **only** by a responder action. CSI can never set it |

- A doorway exit is recorded in the trail and lowers search priority, but never clears a room (others may still be inside).
- A room never leaves MOTION LAST SEEN or UNVERIFIED for RESPONDER-MARKED without a responder action.
- Room states cannot be labelled in recordings. They are validated by replaying scripted scenarios (section 6b).

## 2. Data rules

- Consenting teammates only, in the mock room.
- Raw CSI recordings stay on the dev machine and are git-ignored (`data/`). Do not commit them.
- Every recording has a **session ID**, recorded in a manifest.
- Do not store MAC addresses in manifests or exported datasets. Strip `tx_mac` when saving.

### Manifest (`data/manifest.csv`)

```
session_id,label,person,layout,path_or_speed,date,duration_s,split
S01,motion,A,L1,slow_walk,2026-10-24,120,train
```

## 3. Recording protocol

Each session is about 2 minutes, one label per session.

| Split | Sessions per class | Notes |
|-------|--------------------|-------|
| train | 3 | Vary person, speed, path |
| val | 1 | Differs from train in at least one factor |
| test | 1 | Recorded last. Not touched until the final report |

Minimum total: 5 sessions x 3 classes x 2 min = 30 min of recording.

Per-session checklist:
- [ ] Trim the first and last 5 s (setup and exit noise).
- [ ] Nodes in the same position as the demo, unless the factor is "layout".
- [ ] Heartbeat `pps` is steady (about 100). Discard sessions with large `seq` gaps.
- [ ] Add a row to the manifest right away.

Factors to vary between sessions: person, walking speed, path, furniture layout, node placement, time of day.

If time is short, use a 3-session-per-class minimum and rely on leave-one-session-out (section 5).

## 4. Windowing without leakage

- Window 1.5 s (about 150 packets), 50% overlap.
- Windows are built **inside one session only**.
- Splitting is always by `session_id`. Never shuffle windows across sessions.
- If one recording must be split into blocks, use contiguous blocks (60/20/20) and drop 2 s of windows at each boundary.
- Normalize with statistics fitted on the **training sessions only**, then apply them to val and test.

## 5. Cross-validation

Leave-one-session-out (LOSO), or group k-fold if there are many sessions.

```
for held_out in sessions:
    train = all sessions except held_out
    fit scaler on train
    train model on train
    evaluate on held_out windows
report mean and spread across folds
```

Rules:
- Use `sklearn.model_selection.LeaveOneGroupOut` or `GroupKFold` with `groups=session_id`.
- Every class must appear in the training part of a fold; skip a fold otherwise.
- Hyperparameters are chosen with LOSO on the **train + val** sessions only.
- The test sessions are scored once, at the end, with the final model.
- Better: leave out a whole **person** (leave-one-person-out) to estimate generalization to new people.

## 6. Metrics

- Per-class recall and precision.
- Confusion matrix, summed over folds.
- The key error is **missed motion** (`motion` predicted as `no_motion_seen`). Report it separately.
- Mean and standard deviation of macro-F1 across folds. A large spread means the model is not stable.
- Sanity checks:
  - A `no_motion_seen` recording from another day stays `no_motion_seen`.
  - Baselines (majority class, and a simple variance threshold) are reported next to the model. The model must beat them.

## 6b. State machine validation (scripted replay)

Replay recorded or simulated sessions through the state machine and assert the resulting states.

| Scenario | Expected |
|----------|----------|
| Walk in, keep moving | MOTION NOW |
| Walk in, then stop | MOTION NOW, then MOTION LAST SEEN with growing age |
| Walk in, then doorway exit seen | MOTION LAST SEEN (not cleared), exit logged in trail |
| Node heartbeat lost | UNVERIFIED |
| Low model confidence | UNVERIFIED |
| Never any data | UNVERIFIED |
| Responder marks room | RESPONDER-MARKED |
| Motion after responder mark | Back to MOTION NOW |

Hypothesis properties:
- No sequence of CSI-derived events ever produces RESPONDER-MARKED.
- Silence alone (no motion) never produces RESPONDER-MARKED.
- A room never becomes exited without a doorway-crossing event; trails only move between adjacent rooms.
- Output has no identifier fields and nothing finer than room level.
- No incident data is stored when no incident is open.

## 7. Deliverables

- [ ] `ml/collect/`: capture script that writes a session file and a manifest row (no MACs).
- [ ] `ml/features.py`: pure windowing and feature functions (shared with the Pi runtime).
- [ ] `ml/eval.py`: LOSO and group k-fold, confusion matrix, per-class report.
- [ ] Hypothesis tests: windows never cross sessions, splits never share a session, no MAC field in exported data.
- [ ] `pi/room_state.py` (or equivalent): pure state-machine function plus the section 6b tests.
- [ ] A results table in the README, written honestly: "validated on held-out sessions from N teammates in one mock room".

## 8. Schedule (about 2 hours)

| Step | Time |
|------|------|
| Write the recorder and manifest | 20 min |
| Record 15 sessions | 45 min |
| Features and windowing | 20 min |
| LOSO eval and baseline | 25 min |
| Final test score and write-up | 10 min |

## 9. Open questions

- How many teammates are available for recording?
- Are doorway-crossing sessions needed for the demo?
- Is doorway-exit detection reliable enough to log? If not, drop `doorway_crossing` and exits.
- What confidence threshold sends a room to UNVERIFIED?
- Will the model run on the Pi (dev only) or on the node (privacy-preserving)?

Record decisions in `CONTEXT.md` and log the Kiro usage there too.
