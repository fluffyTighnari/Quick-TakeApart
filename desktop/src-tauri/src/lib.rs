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
                        set_splash_text(&app_handle, "引擎启动超时，日志见 %LOCALAPPDATA%\\Quick-TakeApart\\backend.log");
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

/// Resource layout produced by `prepare-runtime.ps1`:
/// `runtime/{server/{serve.py,engine,web/dist,node_modules/pyright},node/node.exe,python/}`
fn find_runtime() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("runtime"));
            candidates.push(dir.join("resources").join("runtime"));
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
        && path.join("python").join("python.exe").is_file()
        && path.join("node").join("node.exe").is_file()
}

fn free_port() -> u16 {
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(0)
}

fn log_file() -> Option<File> {
    let dir = std::env::var("LOCALAPPDATA").ok().map(|base| {
        PathBuf::from(base).join("Quick-TakeApart")
    })?;
    std::fs::create_dir_all(&dir).ok()?;
    File::create(dir.join("backend.log")).ok()
}

fn spawn_backend(dir: &Path, port: u16) -> std::io::Result<Child> {
    use std::os::windows::process::CommandExt;

    let python = dir.join("python").join("python.exe");
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
        .stdout(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW);

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
    let existing = std::env::var("PATH").unwrap_or_default();
    format!("{};{}", node_dir.display(), existing)
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
