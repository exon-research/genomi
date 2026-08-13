"use strict";

function indexBy(records, key) {
  return new Map(
    records.map((item) => [String(item && item[key] || ""), item]).filter(([id]) => id)
  );
}

/** Build an immutable lookup for exactly one profile render. */
export function createProfileEntityLookup({artifacts = [], specimens = [], assays = []}) {
  const artifactsById = indexBy(artifacts, "artifact_id");
  const specimensById = indexBy(specimens, "specimen_id");
  const assaysById = indexBy(assays, "assay_id");
  return Object.freeze({
    artifact(value) {
      return artifactsById.get(String(value || "")) || null;
    },
    specimen(value) {
      return specimensById.get(String(value || "")) || null;
    },
    assay(value) {
      return assaysById.get(String(value || "")) || null;
    },
  });
}
