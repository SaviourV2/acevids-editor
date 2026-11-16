import { describe, it, expect } from "vitest";
import {
  MAX_PROJECT_FPS,
  MEDIA_DIALOG_FILTERS,
  canvasForVideo,
  classifyMediaExtension,
  fileNameFromPath,
} from "./media";

describe("classifyMediaExtension", () => {
  it.each([
    ["C:\\clips\\Intro.MP4", "video"],
    ["/x/y.webm", "video"],
    ["song.m4a", "audio"],
    ["voice.WAV", "audio"],
    ["photo.jpeg", "image"],
    ["sticker.webp", "image"],
  ])("%s -> %s", (path, kind) => {
    expect(classifyMediaExtension(path)).toBe(kind);
  });

  it("rejects unknown and extension-less files", () => {
    expect(classifyMediaExtension("notes.txt")).toBeNull();
    expect(classifyMediaExtension("README")).toBeNull();
    // A dot in a directory name must not be mistaken for an extension.
    expect(classifyMediaExtension("/v1.mp4/file")).toBeNull();
  });
});

describe("fileNameFromPath", () => {
  it("handles both separators and empty input", () => {
    expect(fileNameFromPath("C:\\a\\b.mp4")).toBe("b.mp4");
    expect(fileNameFromPath("/a/b.mp4")).toBe("b.mp4");
    expect(fileNameFromPath("")).toBe("Media");
  });
});

describe("canvasForVideo", () => {
  it("takes the video's shape with even dimensions and a whole frame rate", () => {
    expect(canvasForVideo({ width: 1512, height: 2688, fps: 59.94 }, 30)).toEqual({
      width: 1512,
      height: 2688,
      fps: 60,
    });
    expect(canvasForVideo({ width: 1081, height: 607, fps: 23.976 }, 30)).toEqual({
      width: 1080,
      height: 606,
      fps: 24,
    });
  });

  it("keeps the fallback rate when the file reports none and caps extreme ones", () => {
    expect(canvasForVideo({ width: 640, height: 360, fps: 0 }, 30)?.fps).toBe(30);
    expect(canvasForVideo({ width: 640, height: 360, fps: NaN }, 25)?.fps).toBe(25);
    expect(canvasForVideo({ width: 640, height: 360, fps: 960 }, 30)?.fps).toBe(MAX_PROJECT_FPS);
  });

  it("is null when the picture size is unknown", () => {
    expect(canvasForVideo({ width: 0, height: 0, fps: 30 }, 30)).toBeNull();
    expect(canvasForVideo({ width: 1920, height: NaN, fps: 30 }, 30)).toBeNull();
    expect(canvasForVideo({ width: 1, height: 1080, fps: 30 }, 30)).toBeNull();
  });
});

describe("MEDIA_DIALOG_FILTERS", () => {
  it("the combined filter includes every per-type extension", () => {
    const [all, ...rest] = MEDIA_DIALOG_FILTERS;
    for (const f of rest) {
      for (const ext of f.extensions) expect(all!.extensions).toContain(ext);
    }
  });
});
