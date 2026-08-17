import { describe, expect, it } from "vitest";
import { fmtBytes, fmtDate, fmtHours, fmtNum, fmtPlaytime, fmtRelative } from "./format";

describe("fmtHours", () => {
  it("treats a non-positive figure as missing, not as zero hours", () => {
    // the HLTB enrichment stores -1 in hltb_main when a lookup found nothing,
    // so this is a real value that reaches the UI
    expect(fmtHours(-1)).toBeNull();
    expect(fmtHours(0)).toBeNull();
    expect(fmtHours(null)).toBeNull();
    expect(fmtHours(undefined)).toBeNull();
  });

  it("drops a trailing zero decimal", () => {
    expect(fmtHours(3)).toBe("3h");
    expect(fmtHours(3.0)).toBe("3h");
  });

  it("keeps a meaningful decimal", () => {
    expect(fmtHours(12.5)).toBe("12.5h");
  });
});

describe("fmtPlaytime", () => {
  it("is null for no recorded time", () => {
    expect(fmtPlaytime(0)).toBeNull();
    expect(fmtPlaytime(null)).toBeNull();
    expect(fmtPlaytime(undefined)).toBeNull();
  });

  it("shows minutes alone under an hour", () => {
    expect(fmtPlaytime(45)).toBe("45m");
  });

  it("shows hours and minutes together", () => {
    expect(fmtPlaytime(90)).toBe("1h 30m");
  });

  it("drops the minutes once the hours get long enough not to care", () => {
    expect(fmtPlaytime(100 * 60 + 30)).toBe("100h");
  });

  it("omits an exact-zero minute remainder", () => {
    expect(fmtPlaytime(120)).toBe("2h");
  });
});

describe("fmtDate", () => {
  it("formats an ISO date", () => {
    expect(fmtDate("2026-08-14T10:00:00Z")).toBe("14 Aug 2026");
  });

  it("is null for missing or unparseable input", () => {
    expect(fmtDate(null)).toBeNull();
    expect(fmtDate(undefined)).toBeNull();
    expect(fmtDate("not a date")).toBeNull();
  });
});

describe("fmtRelative", () => {
  it("says never when there is no timestamp", () => {
    expect(fmtRelative(null)).toBe("never");
  });

  it("describes recent times in the largest sensible unit", () => {
    const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
    expect(fmtRelative(ago(5_000))).toBe("just now");
    expect(fmtRelative(ago(5 * 60_000))).toBe("5m ago");
    expect(fmtRelative(ago(3 * 3_600_000))).toBe("about 3h ago");
    expect(fmtRelative(ago(3 * 86_400_000))).toBe("3d ago");
  });
});

describe("fmtNum", () => {
  it("groups thousands and treats missing as zero", () => {
    expect(fmtNum(1058)).toBe("1,058");
    expect(fmtNum(null)).toBe("0");
    expect(fmtNum(undefined)).toBe("0");
  });
});

describe("fmtBytes", () => {
  it("keeps raw bytes below a kilobyte", () => {
    expect(fmtBytes(512)).toBe("512 B");
  });

  it("steps up through the units", () => {
    expect(fmtBytes(1024)).toBe("1.0 KB");
    expect(fmtBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(fmtBytes(3 * 1024 ** 3)).toBe("3.0 GB");
  });

  it("drops the decimal once the number is large enough to be noise", () => {
    expect(fmtBytes(20 * 1024 * 1024)).toBe("20 MB");
  });
});
