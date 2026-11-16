/**
 * Media file classification for the editor's import flow.
 */
import type { ClipType, ProjectSettings } from "@/types/editor";

/** Extensions imported as video clips. */
export const VIDEO_EXTENSIONS = ["mp4", "mkv", "avi", "mov", "webm"] as const;
/** Extensions imported as audio clips. */
export const AUDIO_EXTENSIONS = ["mp3", "wav", "ogg", "m4a"] as const;
/** Extensions imported as still-image clips. */
export const IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp"] as const;

/** Seconds an imported still image lasts on the timeline. */
export const DEFAULT_IMAGE_DURATION = 5;
/** Fallback length when the backend cannot report a media duration. */
export const FALLBACK_MEDIA_DURATION = 60;

/** Highest frame rate a project takes over from a source file. */
export const MAX_PROJECT_FPS = 120;

/** Frame size and rate of a project canvas. */
export type ProjectCanvas = Pick<ProjectSettings, "width" | "height" | "fps">;

/**
 * Canvas for a project whose first video has the given picture, so a vertical
 * clip gets a vertical project instead of black bars in a 16:9 frame.
 *
 * @param video - Display size and frame rate reported for the file.
 * @param fallbackFps - Frame rate to keep when the file reports none.
 * @returns The canvas (even dimensions, whole fps), or `null` when the size is unknown.
 */
export function canvasForVideo(
  video: { width: number; height: number; fps: number },
  fallbackFps: number
): ProjectCanvas | null {
  if (!(video.width >= 2) || !(video.height >= 2)) return null;
  const even = (n: number) => Math.floor(n / 2) * 2;
  const fps = Math.round(video.fps);
  return {
    width: even(video.width),
    height: even(video.height),
    fps: fps >= 1 ? Math.min(fps, MAX_PROJECT_FPS) : fallbackFps,
  };
}

/** File-type filters for the "Import from disk" dialog. */
export const MEDIA_DIALOG_FILTERS = [
  {
    name: "Media Files",
    extensions: [...VIDEO_EXTENSIONS, ...AUDIO_EXTENSIONS, ...IMAGE_EXTENSIONS],
  },
  { name: "Video", extensions: [...VIDEO_EXTENSIONS] },
  { name: "Audio", extensions: [...AUDIO_EXTENSIONS] },
  { name: "Images", extensions: [...IMAGE_EXTENSIONS] },
];

/** Kind of media a file holds, as far as the editor cares. */
export type MediaKind = Exclude<ClipType, "text">;

/**
 * Classify a path by its extension (case-insensitive).
 *
 * @param path - File path or name.
 * @returns The media kind, or `null` for unsupported files.
 * @example
 * classifyMediaExtension("C:\\clips\\Intro.MP4"); // "video"
 */
export function classifyMediaExtension(path: string): MediaKind | null {
  const name = fileNameFromPath(path);
  const dot = name.lastIndexOf(".");
  if (dot < 0) return null;
  const ext = name.slice(dot + 1).toLowerCase();
  if ((VIDEO_EXTENSIONS as readonly string[]).includes(ext)) return "video";
  if ((AUDIO_EXTENSIONS as readonly string[]).includes(ext)) return "audio";
  if ((IMAGE_EXTENSIONS as readonly string[]).includes(ext)) return "image";
  return null;
}

/**
 * Last path segment, accepting both `/` and `\` separators.
 *
 * @param path - File path.
 * @returns The file name, or `"Media"` for an empty path.
 */
export function fileNameFromPath(path: string): string {
  return path.split(/[/\\]/).pop() || "Media";
}
