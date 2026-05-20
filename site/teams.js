// Färgkodning per åldersklass (klass-fältet från procup.se).
// Klasser uppgår dynamiskt från data; mappningen är best-effort, fallback grå.
const CLASS_COLORS = {
  "F09":    { bg: "#f97316", fg: "#0b0b0f" }, // orange
  "P09":    { bg: "#fb7185", fg: "#0b0b0f" }, // rose
  "F10":    { bg: "#fbbf24", fg: "#0b0b0f" }, // amber
  "P10":    { bg: "#fde047", fg: "#0b0b0f" }, // yellow
  "F11":    { bg: "#a3e635", fg: "#0b0b0f" }, // lime
  "P11":    { bg: "#84cc16", fg: "#0b0b0f" }, // green
  "F12":    { bg: "#22d3ee", fg: "#0b0b0f" }, // cyan
  "P12":    { bg: "#38bdf8", fg: "#0b0b0f" }, // sky
  "F14/13": { bg: "#818cf8", fg: "#0b0b0f" }, // indigo
  "P14/13": { bg: "#a78bfa", fg: "#0b0b0f" }, // violet
  "F16/15": { bg: "#e879f9", fg: "#0b0b0f" }, // fuchsia
  "P16/15": { bg: "#f472b6", fg: "#0b0b0f" }, // pink
  "F19/17": { bg: "#fb923c", fg: "#0b0b0f" }, // orange-400
  "P19/17": { bg: "#ef4444", fg: "#fff" }     // red
};

function classColor(klass) {
  return CLASS_COLORS[klass] || { bg: "#64748b", fg: "#fff" };
}

// Squad-suffix kort form: "HK Järnvägen:3 F8 gul" -> "3 F8 gul", "HK Järnvägen" -> ""
function squadSuffix(rawTeam) {
  if (!rawTeam) return "";
  const s = rawTeam.replace(/^HK J[äa]rnv[äa]gen/i, "").trim();
  return s.replace(/^[:\s-]+/, "").trim();
}

// Etikett för matchkortet: "F12" eller "F12 · :2" om det finns ett squad-suffix
function teamLabel(klass, rawTeam) {
  const suffix = squadSuffix(rawTeam);
  return suffix ? `${klass} · ${suffix}` : klass;
}

window.JVC_TEAMS = { CLASS_COLORS, classColor, squadSuffix, teamLabel };
