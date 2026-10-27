"use strict";

// Marketplace labels sometimes append a visual separator to the final
// control. It is presentation chrome, not part of the selected variant.
function controlKey(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[+-]?\s*\d[\d\s\u00a0]*(?:[.,]\d+)?\s*(?:₽|руб|RUB)(?:\s+за\s+.+)?$/i, "")
    .replace(/[|·•]+\s*$/g, "")
    .trim();
}

module.exports = { controlKey };
