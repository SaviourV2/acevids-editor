//! Error types for ACEVIDS
//!
//! This module defines all error types used throughout the application and the
//! `{ code, message }` wire shape Tauri commands send to the frontend.

use serde::Serialize;
use thiserror::Error;

/// Application-wide error type
#[derive(Error, Debug)]
pub enum AcevidsError {
    /// Filesystem or other I/O failure.
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    /// SQLite failure.
    #[error("Database error: {0}")]
    Database(#[from] rusqlite::Error),

    /// JSON (de)serialization failure.
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    /// Network/HTTP failure.
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),

    /// Malformed URL.
    #[error("URL parse error: {0}")]
    UrlParse(#[from] url::ParseError),

    /// URL is not a recognised YouTube link.
    #[error("Invalid YouTube URL: {0}")]
    InvalidYouTubeUrl(String),

    /// Requested video does not exist.
    #[error("Video not found: {0}")]
    VideoNotFound(String),

    /// A download finished unsuccessfully.
    #[error("Download failed: {0}")]
    DownloadFailed(String),

    /// An editor export finished unsuccessfully.
    #[error("Export failed: {0}")]
    ExportFailed(String),

    /// A required external binary (ffmpeg, yt-dlp, ...) is missing.
    #[error("Binary not found: {0}")]
    BinaryNotFound(String),

    /// An external binary ran but failed.
    #[error("Binary execution failed: {0}")]
    BinaryExecutionFailed(String),

    /// Spawning or managing a child process failed.
    #[error("Process error: {0}")]
    ProcessError(String),

    /// Legacy configuration error variant; prefer [`AcevidsError::Config`].
    #[error("Config error: {0}")]
    ConfigError(String),

    /// Requested editor project does not exist.
    #[error("Project not found: {0}")]
    ProjectNotFound(String),

    /// A path was malformed or could not be resolved.
    #[error("Invalid path: {0}")]
    InvalidPath(String),

    /// The OS refused access.
    #[error("Permission denied: {0}")]
    PermissionDenied(String),

    /// The user cancelled the operation.
    #[error("Cancelled by user")]
    Cancelled,

    /// Error surfaced by the Tauri runtime.
    #[error("Tauri error: {0}")]
    Tauri(#[from] tauri::Error),

    /// Catch-all with a free-form message.
    #[error("{0}")]
    Other(String),

    /// FFmpeg invocation failure.
    #[error("FFmpeg error: {0}")]
    FFmpeg(String),

    /// yt-dlp invocation failure.
    #[error("yt-dlp error: {0}")]
    Ytdlp(String),

    /// Download queue/state error.
    #[error("Download error: {0}")]
    Download(String),

    /// Library (database-backed video list) error.
    #[error("Library error: {0}")]
    Library(String),

    /// Configuration load/save/validation error.
    #[error("Config error: {0}")]
    Config(String),
}

impl AcevidsError {
    /// Stable machine-readable code for this error.
    ///
    /// The frontend matches on these strings, so they must never change for an
    /// existing variant.
    ///
    /// # Example
    /// ```
    /// use acevids_lib::error::AcevidsError;
    /// assert_eq!(AcevidsError::Cancelled.code(), "CANCELLED");
    /// ```
    pub fn code(&self) -> &'static str {
        match self {
            AcevidsError::Io(_) => "IO_ERROR",
            AcevidsError::Database(_) => "DATABASE_ERROR",
            AcevidsError::Json(_) => "JSON_ERROR",
            AcevidsError::Http(_) => "HTTP_ERROR",
            AcevidsError::UrlParse(_) => "URL_PARSE_ERROR",
            AcevidsError::InvalidYouTubeUrl(_) => "INVALID_YOUTUBE_URL",
            AcevidsError::VideoNotFound(_) => "VIDEO_NOT_FOUND",
            AcevidsError::DownloadFailed(_) => "DOWNLOAD_FAILED",
            AcevidsError::ExportFailed(_) => "EXPORT_FAILED",
            AcevidsError::BinaryNotFound(_) => "BINARY_NOT_FOUND",
            AcevidsError::BinaryExecutionFailed(_) => "BINARY_EXECUTION_FAILED",
            AcevidsError::ProcessError(_) => "PROCESS_ERROR",
            AcevidsError::ConfigError(_) => "CONFIG_ERROR",
            AcevidsError::ProjectNotFound(_) => "PROJECT_NOT_FOUND",
            AcevidsError::InvalidPath(_) => "INVALID_PATH",
            AcevidsError::PermissionDenied(_) => "PERMISSION_DENIED",
            AcevidsError::Cancelled => "CANCELLED",
            AcevidsError::Tauri(_) => "TAURI_ERROR",
            AcevidsError::Other(_) => "UNKNOWN_ERROR",
            AcevidsError::FFmpeg(_) => "FFMPEG_ERROR",
            AcevidsError::Ytdlp(_) => "YTDLP_ERROR",
            AcevidsError::Download(_) => "DOWNLOAD_ERROR",
            AcevidsError::Library(_) => "LIBRARY_ERROR",
            AcevidsError::Config(_) => "CONFIG_ERROR",
        }
    }
}

/// Serializable error for frontend
#[derive(Serialize, Debug)]
pub struct ErrorResponse {
    /// Stable machine-readable code, see [`AcevidsError::code`].
    pub code: String,
    /// Human-readable message, identical to the error's `Display` output.
    pub message: String,
}

impl From<&AcevidsError> for ErrorResponse {
    fn from(error: &AcevidsError) -> Self {
        ErrorResponse {
            code: error.code().to_string(),
            message: error.to_string(),
        }
    }
}

impl From<AcevidsError> for ErrorResponse {
    fn from(error: AcevidsError) -> Self {
        ErrorResponse::from(&error)
    }
}

// Tauri commands serialize their error type straight to the frontend, so the
// wire shape is the `{ code, message }` object rather than a bare string.
impl Serialize for AcevidsError {
    fn serialize<S>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        ErrorResponse::from(self).serialize(serializer)
    }
}

/// Result type alias for ACEVIDS operations
pub type Result<T> = std::result::Result<T, AcevidsError>;

impl From<anyhow::Error> for AcevidsError {
    fn from(error: anyhow::Error) -> Self {
        AcevidsError::Other(error.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn every_variant() -> Vec<(AcevidsError, &'static str)> {
        let io = std::io::Error::new(std::io::ErrorKind::NotFound, "missing");
        let json = serde_json::from_str::<i32>("not json").unwrap_err();
        let url = url::Url::parse("").unwrap_err();
        let http = reqwest::Client::new()
            .get("::not a url::")
            .build()
            .unwrap_err();
        vec![
            (AcevidsError::Io(io), "IO_ERROR"),
            (
                AcevidsError::Database(rusqlite::Error::QueryReturnedNoRows),
                "DATABASE_ERROR",
            ),
            (AcevidsError::Json(json), "JSON_ERROR"),
            (AcevidsError::Http(http), "HTTP_ERROR"),
            (AcevidsError::UrlParse(url), "URL_PARSE_ERROR"),
            (
                AcevidsError::InvalidYouTubeUrl("u".into()),
                "INVALID_YOUTUBE_URL",
            ),
            (AcevidsError::VideoNotFound("v".into()), "VIDEO_NOT_FOUND"),
            (AcevidsError::DownloadFailed("d".into()), "DOWNLOAD_FAILED"),
            (AcevidsError::ExportFailed("e".into()), "EXPORT_FAILED"),
            (AcevidsError::BinaryNotFound("b".into()), "BINARY_NOT_FOUND"),
            (
                AcevidsError::BinaryExecutionFailed("b".into()),
                "BINARY_EXECUTION_FAILED",
            ),
            (AcevidsError::ProcessError("p".into()), "PROCESS_ERROR"),
            (AcevidsError::ConfigError("c".into()), "CONFIG_ERROR"),
            (
                AcevidsError::ProjectNotFound("p".into()),
                "PROJECT_NOT_FOUND",
            ),
            (AcevidsError::InvalidPath("p".into()), "INVALID_PATH"),
            (
                AcevidsError::PermissionDenied("p".into()),
                "PERMISSION_DENIED",
            ),
            (AcevidsError::Cancelled, "CANCELLED"),
            (
                AcevidsError::Tauri(tauri::Error::WindowNotFound),
                "TAURI_ERROR",
            ),
            (AcevidsError::Other("o".into()), "UNKNOWN_ERROR"),
            (AcevidsError::FFmpeg("f".into()), "FFMPEG_ERROR"),
            (AcevidsError::Ytdlp("y".into()), "YTDLP_ERROR"),
            (AcevidsError::Download("d".into()), "DOWNLOAD_ERROR"),
            (AcevidsError::Library("l".into()), "LIBRARY_ERROR"),
            (AcevidsError::Config("c".into()), "CONFIG_ERROR"),
        ]
    }

    #[test]
    fn every_variant_has_a_stable_code() {
        for (error, code) in every_variant() {
            assert_eq!(error.code(), code, "{error:?}");
        }
    }

    #[test]
    fn serialize_and_error_response_agree() {
        for (error, code) in every_variant() {
            let message = error.to_string();
            let json = serde_json::to_value(&error).unwrap();
            assert_eq!(json["code"], code);
            assert_eq!(json["message"], message);

            let response = ErrorResponse::from(error);
            assert_eq!(response.code, code);
            assert_eq!(response.message, message);
        }
    }

    #[test]
    fn display_messages_include_context() {
        assert_eq!(AcevidsError::Cancelled.to_string(), "Cancelled by user");
        assert_eq!(AcevidsError::Other("raw".into()).to_string(), "raw");
        assert_eq!(
            AcevidsError::Download("boom".into()).to_string(),
            "Download error: boom"
        );
    }

    #[test]
    fn from_conversions_pick_the_matching_variant() {
        let e: AcevidsError = std::io::Error::other("x").into();
        assert!(matches!(e, AcevidsError::Io(_)));
        let e: AcevidsError = serde_json::from_str::<i32>("x").unwrap_err().into();
        assert!(matches!(e, AcevidsError::Json(_)));
        let e: AcevidsError = url::Url::parse("").unwrap_err().into();
        assert!(matches!(e, AcevidsError::UrlParse(_)));
        let e: AcevidsError = rusqlite::Error::InvalidQuery.into();
        assert!(matches!(e, AcevidsError::Database(_)));
        let e: AcevidsError = anyhow::anyhow!("wrapped").into();
        assert!(matches!(e, AcevidsError::Other(ref m) if m == "wrapped"));
        let e: AcevidsError = tauri::Error::WindowNotFound.into();
        assert!(matches!(e, AcevidsError::Tauri(_)));
    }
}
