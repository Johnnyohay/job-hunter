// The facts Claude reads out of each posting (.claude/commands/daily.md, step 2), checked and turned into
// tracker columns. Claude does the reading, so no format of any job board or posting is hard-coded here.

export const WORKPLACES = ["Remote", "Hybrid", "Onsite", "Flexible", "Unknown"] as const;

export interface Facts {
  workplace: (typeof WORKPLACES)[number];
  /** The primary place: the listed location that best matches my preferences. null for remote-only jobs. */
  place: { city: string; state: string; country: string; lat: number; lng: number } | null;
  /** Remote-only jobs: where they hire, e.g. "United States". */
  remote_region: string;
  location_count: number;
  /** Base pay as stated (never inferred); null when the posting states none. */
  pay: { min: number; max: number; currency: string; period: "year" | "hour"; as_posted: string } | null;
}

const HOURS_PER_YEAR = 2080;

/** Returns what's wrong with a facts object, or nothing. */
export function factsProblems(f: Facts | undefined): string[] {
  if (!f) return ["missing facts"];
  const problems: string[] = [];
  if (!WORKPLACES.includes(f.workplace)) problems.push(`workplace "${f.workplace}"`);
  if (f.place) {
    const { lat, lng } = f.place;
    if (!f.place.city || !f.place.country) problems.push("place without city or country");
    if (!(Math.abs(lat) <= 90 && Math.abs(lng) <= 180)) problems.push(`coordinates ${lat},${lng}`);
  }
  if (f.pay) {
    const { min, max, period } = f.pay;
    if (!(min > 0 && max >= min)) problems.push(`pay ${min}-${max}`);
    if (period !== "year" && period !== "hour") problems.push(`pay period "${period}"`);
  }
  return problems;
}

/** The tracker columns for a posting's facts (pay annualized). */
export function factColumns(f: Facts | undefined, postedLocation: string) {
  const perYear = f?.pay?.period === "hour" ? HOURS_PER_YEAR : 1;
  return {
    Workplace: f?.workplace ?? "",
    City: f?.place?.city ?? "",
    State: f?.place?.state ?? "",
    Country: f?.place?.country ?? f?.remote_region ?? "",
    Latitude: f?.place ? String(f.place.lat) : "",
    Longitude: f?.place ? String(f.place.lng) : "",
    "# Locations": f ? String(f.location_count) : "",
    "Locations (as posted)": postedLocation,
    "Comp Min": f?.pay ? String(Math.round(f.pay.min * perYear)) : "",
    "Comp Max": f?.pay ? String(Math.round(f.pay.max * perYear)) : "",
    Currency: f?.pay?.currency ?? "",
    "Comp (as posted)": f?.pay?.as_posted ?? "",
  };
}
