//! Desktop shell: start the local Python engine, then hand the window over to it.
//!
//! The Python server already serves the built frontend (`web/dist`) and the API
//! from one origin, so the shell only has to spawn it and point a webview at
//! `http://127.0.0.1:<port>/`. No Tauri IPC and no frontend changes are needed.

use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(120);

struct Backend(Mutex<Option<Child>>);

pub fn run() {
    let app = tauri::Builder::default()
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let runtime = find_runtime();
            let port = free_port();

            match runtime {
                Some(dir) => match spawn_backend(&dir, port) {
                    Ok(child) => {
                        *app.state::<Backend>().0.lock().unwrap() = Some(child);
                    }
                    Err(exc) => {
                        show_fatal(app.handle().clone(), format!("无法启动本地引擎：{exc}"));
                        return Ok(());
                    }
                },
                None => {
                    show_fatal(
                        app.handle().clone(),
                        "未找到 runtime 目录（Python / node / pyright 未随应用打包）。".into(),
                    );
                    return Ok(());
                }
            }

            let splash = WebviewWindowBuilder::new(app, "splash", WebviewUrl::App("index.html".into()))
                .title("Quick-TakeApart")
                .inner_size(560.0, 320.0)
                .resizable(false)
                .center()
                .build()?;

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let deadline = Instant::now() + STARTUP_TIMEOUT;
                let mut healthy = false;
                while Instant::now() < deadline {
                    if probe_health(port) {
                        healthy = true;
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(250));
                }

                let app_handle = handle.clone();
                let _ = handle.run_on_main_thread(move || {
                    if healthy {
                        open_main(&app_handle, port);
                    } else {
                        let hint = log_path_hint();
                        set_splash_text(
                            &app_handle,
                            &format!("引擎启动超时，日志见 {hint}"),
                        );
                    }
                });
            });

            let _ = splash.show();
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = app_handle.state::<Backend>().0.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}

fn open_main(app: &tauri::AppHandle, port: u16) {
    let url = match format!("http://127.0.0.1:{port}/").parse() {
        Ok(url) => url,
        Err(_) => return,
    };
    let built = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        .title("Quick-TakeApart")
        .inner_size(1440.0, 900.0)
        .min_inner_size(960.0, 640.0)
        .build();
    if built.is_ok() {
        if let Some(splash) = app.get_webview_window("splash") {
            let _ = splash.close();
        }
    }
}

fn set_splash_text(app: &tauri::AppHandle, message: &str) {
    if let Some(window) = app.get_webview_window("splash") {
        let escaped = message.replace('\\', "\\\\").replace('\'', "\\'");
        let _ = window.eval(&format!(
            "var s=document.getElementById('status');if(s){{s.textContent='{escaped}';s.classList.add('error');}}"
        ));
    }
}

fn show_fatal(app: tauri::AppHandle, message: String) {
    let _ = WebviewWindowBuilder::new(&app, "splash", WebviewUrl::App("index.html".into()))
        .title("Quick-TakeApart")
        .inner_size(560.0, 320.0)
        .resizable(false)
        .center()
        .build();
    set_splash_text(&app, &message);
}

/// Resource layout produced by `prepare-runtime.ps1` (Windows) or
/// `prepare-runtime.mac.sh` (macOS):
/// `runtime/{server/{serve.py,engine,web/dist,node_modules/pyright},node/<node>,python/<interpreter>}`
fn find_runtime() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("runtime"));
            candidates.push(dir.join("resources").join("runtime"));
            // macOS .app bundle: Contents/MacOS/<exe>, resources in Contents/Resources.
            candidates.push(dir.join("..").join("Resources").join("runtime"));
            // `cargo run` puts the binary in target/debug, four levels below src-tauri.
            candidates.push(dir.join("../../../src-tauri/runtime"));
        }
    }
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("runtime"));

    candidates
        .into_iter()
        .find(|path| is_runtime_root(path))
}

fn is_runtime_root(path: &Path) -> bool {
    path.join("server").join("serve.py").is_file()
        && python_exe(path).is_file()
        && node_exe(path).is_file()
}

/// Bundled interpreter: `python/python.exe` on Windows, `python/bin/python3` elsewhere.
fn python_exe(runtime: &Path) -> PathBuf {
    if cfg!(windows) {
        runtime.join("python").join("python.exe")
    } else {
        runtime.join("python").join("bin").join("python3")
    }
}

/// Bundled node binary, used to launch pyright.
fn node_exe(runtime: &Path) -> PathBuf {
    let name = if cfg!(windows) { "node.exe" } else { "node" };
    runtime.join("node").join(name)
}

fn free_port() -> u16 {
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(0)
}

fn log_dir() -> Option<PathBuf> {
    if cfg!(windows) {
        std::env::var("LOCALAPPDATA")
            .ok()
            .map(|base| PathBuf::from(base).join("Quick-TakeApart"))
    } else {
        std::env::var("HOME")
            .ok()
            .map(|home| {
                PathBuf::from(home)
                    .join("Library")
                    .join("Application Support")
                    .join("Quick-TakeApart")
            })
    }
}

fn log_path_hint() -> String {
    match log_dir() {
        Some(dir) => dir.join("backend.log").display().to_string(),
        None => "backend.log".to_string(),
    }
}

fn log_file() -> Option<File> {
    let dir = log_dir()?;
    std::fs::create_dir_all(&dir).ok()?;
    File::create(dir.join("backend.log")).ok()
}

fn spawn_backend(dir: &Path, port: u16) -> std::io::Result<Child> {
    let python = python_exe(dir);
    let server = dir.join("server");
    let node_dir = dir.join("node");

    // pyright is launched as `node langserver.index.js`, so node has to be resolvable.
    let path = prepend_path(&node_dir);

    let mut cmd = Command::new(python);
    cmd.arg("serve.py")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .current_dir(&server)
        .env("PATH", path)
        .env("QTA_PARENT_PID", std::process::id().to_string())
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match log_file() {
        Some(file) => {
            cmd.stderr(Stdio::from(file));
        }
        None => {
            cmd.stderr(Stdio::null());
        }
    }

    cmd.spawn()
}

fn prepend_path(node_dir: &Path) -> String {
    let sep = if cfg!(windows) { ';' } else { ':' };
    let mut parts: Vec<String> = vec![node_dir.display().to_string()];

    // A Finder-launched .app inherits launchd's PATH, which is only
    // /usr/bin:/bin:/usr/sbin:/sbin. None of the user's toolchains (go, gopls,
    // homebrew, cargo) are visible there, so a language server installed by
    // `go install` looks "missing" even though the shell finds it. Rebuild the
    // login-shell path the same way path_helper does, then add per-user dirs.
    #[cfg(not(windows))]
    {
        parts.extend(shell_search_paths());
    }

    let existing = std::env::var("PATH").unwrap_or_default();
    if !existing.is_empty() {
        parts.push(existing);
    }
    parts.join(&sep.to_string())
}

#[cfg(not(windows))]
fn shell_search_paths() -> Vec<String> {
    fn push(out: &mut Vec<String>, value: &str) {
        let value = value.trim();
        if !value.is_empty() && !out.iter().any(|seen| seen == value) {
            out.push(value.to_string());
        }
    }

    let mut out: Vec<String> = Vec::new();

    // /etc/paths plus /etc/paths.d/<name>: this is what path_helper feeds login
    // shells, and it is where the Go pkg installer puts /usr/local/go/bin.
    let mut files: Vec<std::path::PathBuf> = vec![std::path::PathBuf::from("/etc/paths")];
    if let Ok(entries) = std::fs::read_dir("/etc/paths.d") {
        for entry in entries.flatten() {
            files.push(entry.path());
        }
    }
    files.sort();
    for file in files {
        if let Ok(text) = std::fs::read_to_string(&file) {
            for line in text.lines() {
                push(&mut out, line);
            }
        }
    }

    // Per-user and package-manager locations that no shell profile guarantees.
    let home = std::env::var("HOME").unwrap_or_default();
    for dir in [
        "go/bin",
        ".local/bin",
        ".cargo/bin",
        "Library/pnpm",
        ".npm-global/bin",
    ] {
        if !home.is_empty() {
            push(&mut out, &format!("{home}/{dir}"));
        }
    }
    for dir in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/local/go/bin", "/opt/local/bin"] {
        push(&mut out, dir);
    }

    out.retain(|dir| std::path::Path::new(dir).is_dir());
    out
}

fn probe_health(port: u16) -> bool {
    if port == 0 {
        return false;
    }
    let addr = format!("127.0.0.1:{port}");
    let Ok(stream) = TcpStream::connect_timeout(&addr.parse().unwrap(), Duration::from_millis(1000))
    else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(2000)));
    let mut writer = stream.try_clone().ok();
    if let Some(ref mut w) = writer {
        let _ = w.write_all(
            b"GET /api/health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
        );
    }
    let mut reader = BufReader::new(stream);
    let mut status_line = String::new();
    if reader.read_line(&mut status_line).is_err() {
        return false;
    }
    status_line.contains(" 200 ")
}
