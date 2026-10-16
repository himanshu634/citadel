/**
 * What the top bar says about the current company: whether the ask field is open, and the status
 * line on its right.
 *
 * Why: both depend only on the company's status and build, so they are pure functions with tests,
 * and the component just draws them. The status line decides "building" from `company.status`,
 * never from `build`, which may be a finished build.
 */
import { stepOf } from "./build";
import type { Company } from "./types";

export interface AskField {
  disabled: boolean;
  placeholder: string;
}

export interface StatusLine {
  text: string;
  /** When the line states a time: the machine-readable value and the part of `text` that shows it. */
  datetime?: string;
  when?: string;
  tone: "muted" | "warning" | "danger";
}

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
const two = (n: number) => String(n).padStart(2, "0");

/**
 * "6 Feb, 14:32" in local time, with the year ("3 Sep 2025, 23:59") when it is not `now`'s year
 * (design-system.md section 9). Null when `iso` is not a date.
 */
export function formatSynced(
  iso: string,
  now: Date = new Date(),
): string | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const year =
    date.getFullYear() === now.getFullYear() ? "" : ` ${date.getFullYear()}`;
  return `${date.getDate()} ${MONTHS[date.getMonth()]}${year}, ${two(date.getHours())}:${two(date.getMinutes())}`;
}

/** The ask field's state. A failed build keeps asking: the graph still holds the last good load. */
export function askFieldOf(company: Company | undefined): AskField {
  if (!company)
    return { disabled: true, placeholder: "Open a company to ask about it" };
  const { name } = company;
  switch (company.status) {
    case "building":
    case "empty":
      return {
        disabled: true,
        placeholder: `Asking opens when ${name} finishes building`,
      };
    case "invalid":
      return { disabled: true, placeholder: `Fix the config to ask ${name}` };
    case "unknown":
      return {
        disabled: true,
        placeholder: `Asking opens when ${name}'s graph is reachable`,
      };
    default:
      return {
        disabled: false,
        placeholder: `Ask ${name} about people, systems or decisions`,
      };
  }
}

/** The line on the top bar's right; null when no company is current. */
export function statusLineOf(
  company: Company | undefined,
  now: Date = new Date(),
): StatusLine | null {
  if (!company) return null;
  switch (company.status) {
    case "building": {
      const step = company.build ? stepOf(company.build) : null;
      return {
        text: step ? `Building, step ${step.n} of ${step.total}` : "Building",
        tone: "warning",
      };
    }
    case "failed":
      return { text: "Last build failed", tone: "danger" };
    case "invalid":
      return { text: "Config invalid", tone: "danger" };
    case "unknown":
      return { text: "Graph unreachable", tone: "muted" };
    case "empty":
      return { text: "Not built yet", tone: "muted" };
    default: {
      const iso = company.last_synced_at;
      const synced = iso ? formatSynced(iso, now) : null;
      if (!iso || !synced) return { text: "Not synced yet", tone: "muted" };
      return {
        text: `Synced ${synced}`,
        datetime: iso,
        when: synced,
        tone: "muted",
      };
    }
  }
}
