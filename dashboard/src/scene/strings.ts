// Every user-visible literal in the dashboard (Req 9.6, 10.1, 12.5).
// UI code composes text from these values only, so one test can scan them
// all for Banned_Words. Pure, DOM-free.

/** Banned_Word pattern (Req 9.6). No user-visible text may match it. */
export const BANNED = /\b(empty|clear(ed)?|safe)\b/i;

export const STRINGS = {
  // Header
  disclaimer: "Decision support only — does not replace a full search",
  simulatedData: "SIMULATED DATA",
  simulatedTrigger: "SIMULATED TRIGGER",
  view2d: "2D view",
  faults: "faults",
  faultList: "Sensor faults",
  faultCause: "Cause",
  faultAction: "Suggested action",
  noFaults: "No sensor faults",

  // State labels (Req 9.1)
  labelMotion: "MOTION",
  labelPossible: "POSSIBLE",
  labelUnknown: "UNKNOWN",
  labelNoDetection: "NO DETECTION",

  // Confidence bands (Req 9.7), shown as "HIGH 86%"
  bandHigh: "HIGH",
  bandMedium: "MED",
  bandLow: "LOW",

  // Room sub-text and chips
  stillNeedsSweep: "Still needs a sweep",
  noDataFromHub: "No data from hub",
  notOnFloorPlan: "Not on floor plan",
  motionLastSeen: "Motion last seen",
  never: "never",
  ago: "ago",
  lastKnown: "last known",
  stale: "STALE",
  uncalibrated: "Uncalibrated",
  simulated: "SIMULATED",
  searched: "SEARCHED",
  searchedChip: "✓ SEARCHED",
  rank: "rank",

  // Annotations (label text only)
  responderPresent: "Motion · responder present",
  recentMotionMayBeResponder: "Recent motion may be responder",

  // Crew
  near: "Near",
  betweenRooms: "Between rooms",
  notHeard: "not heard",
  lastHeard: "Last heard",
  crew: "crew",

  // Banners
  hubLost: "Hub connection lost — readout is not updating",
  reconnecting: "Reconnecting…",
  allSearched: "No detection rooms still require a sweep",

  // Priority list and room sheet
  priorityList: "Priority",
  markSearched: "Mark searched",
  cancel: "Cancel",
  close: "Close",
  state: "State",
  confidence: "Confidence",
  lastActivity: "Last activity",
  atAlarm: "AT ALARM",
  atAlarmToggle: "At alarm",
  liveView: "Live",
  linkHealth: "Link health",
  linkOk: "OK",
  linkDegraded: "Degraded",
  linkOffline: "Offline",
  sourceEdge: "Edge",
  sourceHub: "Hub",
  modelVersion: "model",
  crewPresent: "Crew present",
  none: "none",

  // Floor tabs
  floor: "Floor",

  // Pairing
  pairTitle: "Pair this phone",
  pairPrompt: "Enter the 6-digit code shown on the laptop",
  pairDelete: "Delete",
  pairWrongCode: "That code did not match. Check the laptop and try again.",
  pairTooManyTries: "Too many tries. Wait a minute, then enter the new code from the laptop.",
  pairSessionEnded: "This phone was signed out. Pair again with the laptop code.",

  // Floor plan errors
  floorPlanErrorTitle: "Floor plan could not be loaded",
  floorPlanErrorHelp: "Fix these problems in hub/config/floorplan.json, then reload:",

  // Laptop controls
  triggerAlarm: "Trigger simulated alarm",
  endIncident: "End incident",
  endIncidentConfirm: "End the incident and reset all rooms?",
  confirm: "Confirm",
  pairPhone: "Pair a phone",
  pairCode: "Pairing code",
  secondsLeft: "s left",
  revokePhones: "Revoke phones",
  revokePhonesConfirm: "Sign out every paired phone?",
  idleTitle: "No active incident",
} as const satisfies Record<string, string>;

export type StringKey = keyof typeof STRINGS;

/** True when `text` contains a Banned_Word. */
export function hasBannedWord(text: string): boolean {
  return BANNED.test(text);
}
