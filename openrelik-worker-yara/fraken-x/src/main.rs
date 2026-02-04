// Some portions Copyright (c) 2024. The YARA-X Authors. All Rights Reserved.

use std::collections::HashMap;
use std::fs::File;
use std::io::BufReader;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::{fs, path::PathBuf, process, sync::atomic::Ordering};

use anyhow::Context;
use crossbeam::channel::Sender;
use fraken_x::magic;
use fraken_x::userid;
use fraken_x::walk::{Message, ParWalker, Walker};
use superconsole::{Component, Lines};

use std::sync::atomic::AtomicUsize;

use clap::{Args, Parser};

use yara_x::{MatchingRules, MetaValue, Scanner, SourceCode};

use yansi::Color::Red;
use yansi::Paint;

use sha256::try_digest;

#[derive(Parser)]
#[command(about, long_about = None)]
struct Cli {
    /// Specify a particular path to a file or folder containing the Yara rules to use
    rules: PathBuf,

    #[command(flatten)]
    testorscan: TestOrScan,

    /// A path under the rules path that contains File Magics
    #[arg(long, default_value = "misc/file-type-signatures.txt")]
    magic: Option<PathBuf>,

    /// Only rules with scores greater than this will be output
    #[arg(long, default_value_t = 40)]
    minscore: u32,

    /// Only files less than this size will be scanned
    #[arg(long, default_value_t = 1073741824)]
    maxsize: u64,
}

#[derive(Args)]
#[group(required = true, multiple = false)]
struct TestOrScan {
    /// Specify a particular folder to be scanned
    #[arg(short, long, group = "testorscan")]
    folder: Option<Vec<PathBuf>>,

    /// Test the rules for syntax validity and then exit
    #[arg(long, group = "testorscan")]
    testrules: bool,
}

// Taken from yara-x/cli/src/commands/scan.rs
struct ScanState {
    num_scanned_files: AtomicUsize,
    num_matching_files: AtomicUsize,
    definitions: Vec<(Vec<u8>, String)>,
    users: HashMap<u32, String>,
}

impl ScanState {
    fn new(definitions: Vec<(Vec<u8>, String)>, users: HashMap<u32, String>) -> Self {
        Self {
            num_scanned_files: AtomicUsize::new(0),
            num_matching_files: AtomicUsize::new(0),
            definitions: definitions,
            users: users,
        }
    }
}

impl Component for ScanState {
    fn draw_unchecked(
        &self,
        _: superconsole::Dimensions,
        _mode: superconsole::DrawMode,
    ) -> anyhow::Result<Lines> {
        let lines = Lines::new();
        // Supress std output.
        Ok(lines)
    }
}

pub trait OutputHandler: Sync {
    /// Called for each scanned file.
    fn on_file_scanned(
        &self,
        file_path: &Path,
        scan_results: MatchingRules<'_, '_>,
        output: &Sender<Message>,
        minimum_score: u32,
    );
    /// Called when the last file has been scanned.
    fn on_done(&self, _output: &Sender<Message>);
}

pub struct JsonOutputHandler {
    output_buffer: std::sync::Arc<std::sync::Mutex<Vec<MatchJson>>>,
}

#[derive(serde::Serialize, Clone)]
#[allow(non_snake_case)]
struct MatchJson {
    ImagePath: String,
    SHA256: String,
    Signature: String,
    Description: String,
    Reference: String,
    Score: i64,
}

impl OutputHandler for JsonOutputHandler {
    fn on_file_scanned(
        &self,
        file_path: &Path,
        scan_results: MatchingRules<'_, '_>,
        _output: &Sender<Message>,
        minimum_score: u32,
    ) {
        let path = file_path
            .canonicalize()
            .ok()
            .as_ref()
            .and_then(|absolute| absolute.to_str())
            .map(|s| s.to_string())
            .unwrap_or_default();

        let mut matches = Vec::new();

        for matching_rule in scan_results.into_iter() {
            let hash = try_digest(file_path).unwrap_or("".to_string());
            let mut output = MatchJson {
                ImagePath: path.clone(),
                SHA256: hash,
                Signature: matching_rule.identifier().to_string(),
                Description: "".to_string(),
                Reference: "".to_string(),
                Score: 50,
            };
            let metadata = matching_rule.metadata();
            for (key, value) in metadata {
                if key == "score" || key == "severity" {
                    // If it's not an Integer or String, ignore it.
                    if let MetaValue::Integer(value) = value {
                        output.Score = value;
                    } else if let MetaValue::String(value) = value {
                        output.Score = value.parse().unwrap_or(50);
                    }
                }
                if key.starts_with("desc") {
                    if let MetaValue::String(value) = value {
                        output.Description = value.to_string();
                    }
                }
                if key == "reference" || key.starts_with("report") {
                    if let MetaValue::String(value) = value {
                        output.Reference = value.to_string();
                    }
                }
                if key == "context" {
                    if let MetaValue::String(value) = value {
                        if value == "yes" || value == "true" || value == "1" {
                            output.Score = 0;
                        }
                    }
                }
            }
            if output.Score >= minimum_score.into() {
                matches.push(output);
            }
        }
        let mut lock = self.output_buffer.lock().unwrap();
        lock.extend(matches);
    }

    fn on_done(&self, output: &Sender<Message>) {
        let matches = {
            let mut lock = self.output_buffer.lock().unwrap();
            std::mem::take(&mut *lock)
        };
        if matches.len() == 0 {
            println!("[]"); // Empty JSON.
            return;
        }
        let rendered_json = serde_json::to_string(&matches).expect("Failed to render JSON");
        let _ = output.send(Message::Info(rendered_json));
    }
}
fn main() {
    let cli = Cli::parse();

    let mut compiler = yara_x::Compiler::new();
    let mut definitions: Vec<(Vec<u8>, String)> = vec![];
    let mut max_signature_len = 0;

    if cli.magic.is_some() {
        eprintln!("[+] Testing existence of magic file");

        let magic_path = cli.rules.join(cli.magic.unwrap_or("".into()).clone());
        if !magic_path.exists() || !magic_path.is_file() {
            eprintln!("[-] Magic file specified but file not found.");
        } else {
            let magic_file = File::open(magic_path).expect("Failed to open magic file");
            let reader = BufReader::new(magic_file);
            (definitions, max_signature_len) =
                magic::parse_definitions_file(reader).expect("Failed to parse magic file");
            eprintln!("[+] {} magics parsed", definitions.len());
        }
    }

    // External vars.
    let vars = vec!["filepath", "filename", "filetype", "extension", "owner"];
    for ident in vars {
        let _ = compiler.define_global(ident, "");
    }

    // Scan the rules dir
    let mut w = Walker::path(cli.rules.as_path());
    w.filter("**/*.yar");
    w.filter("**/*.yara");
    if let Err(err) = w.walk(
        |file_path| {
            eprintln!("[-] Attempting to parse {}", file_path.display());
            let src = fs::read(file_path)
                .with_context(|| format!("can not read `{}`", file_path.display()))?;

            let src = SourceCode::from(src.as_slice())
                .with_origin(file_path.as_os_str().to_str().unwrap());
            let _ = compiler.add_source(src);

            Ok(())
        },
        Err,
    ) {
        eprintln!("Rules parsing error: {}", err);
        process::exit(1);
    }

    for error in compiler.errors() {
        eprintln!("Rule error: {}", error);
    }

    /*for warning in compiler.warnings() {
        eprintln!("{}", warning);
    }*/

    eprintln!("[+] Building the rules");
    // Obtain the compiled YARA rules.
    let rules = compiler.build();

    if cli.testorscan.testrules {
        println!("[+] Rules are valid!");
        process::exit(0);
    }

    eprintln!("[+] Scanning!");
    let path_vec = cli.testorscan.folder.expect("Needs a path");

    for path in path_vec {
        let joined_path = path.join("etc/passwd");
        let full_folder_path = joined_path.to_str().unwrap_or("");
        eprintln!("[+] Parsing /etc/passwd under {}", full_folder_path);
        let users = userid::get_usernames_from_passwd(full_folder_path).unwrap_or(HashMap::new());
        if users.len() == 0 {
            eprintln!("[-] No users found in /etc/passwd");
        } else {
            eprintln!("[+] {} users found", users.len());
        }

        let state = ScanState::new(definitions.clone(), users);

        let w = ParWalker::path(path.as_path());
        let output_handler = JsonOutputHandler {
            output_buffer: Default::default(),
        };
        w.walk(
            state,
            // Init.
            |_, _output| {
                let scanner = Scanner::new(&rules);
                scanner
            },
            // File handler
            |state, output, file_path, scanner| {
                let metadata = fs::metadata(file_path.clone())?;
                if metadata.len() > cli.maxsize {
                    return Ok(());
                }
                if let Some(username) = state.users.get(&metadata.uid()) {
                    scanner.set_global("owner", username.clone())?;
                }

                scanner.set_global("filepath", file_path.to_str().unwrap())?;
                scanner.set_global("filename", file_path.file_name().unwrap().to_str().unwrap())?;
                scanner.set_global(
                    "extension",
                    file_path
                        .extension()
                        .map(|name| name.to_string_lossy().into_owned())
                        .unwrap_or("".to_string()),
                )?;

                // Magics
                let target_bytes =
                // Anyhow
                    magic::read_first_bytes(file_path.to_str().unwrap_or(""), max_signature_len).unwrap_or(vec![]);
                if target_bytes.len() > 0 {
                    for (hex_bytes, description) in &state.definitions {
                        if target_bytes.starts_with(&hex_bytes) {
                            scanner.set_global("filetype", description.clone())?;
                            break;
                        }
                    }
                }

                let scan_results = scanner.scan_file(file_path.as_path());
                let scan_results = scan_results?;
                let matched_count = scan_results.matching_rules().len();
                let matched = scan_results.matching_rules();

                output_handler.on_file_scanned(file_path.as_path(), matched, output, cli.minscore);

                state.num_scanned_files.fetch_add(1, Ordering::Relaxed);
                if matched_count > 0 {
                    state.num_matching_files.fetch_add(1, Ordering::Relaxed);
                }

                // Reset globals
                scanner.set_global("owner", "")?;
                scanner.set_global("filepath", "")?;
                scanner.set_global("filename", "")?;
                scanner.set_global("extension", "")?;
                scanner.set_global("filetype", "")?;

                Ok(())
            },
            // Finalisation
            |_, _| {},
            // Walk done.
            |output| output_handler.on_done(output),
            // Error handler
            |err, _| {
                let error = err.to_string();
                let root_cause = err.root_cause().to_string();
                let msg = if error != root_cause {
                    format!("{} {}: {}", "error: ".paint(Red).bold(), error, root_cause,)
                } else {
                    format!("{}: {}", "error: ".paint(Red).bold(), error)
                };

                eprintln!("{}", msg);

                Ok(())
            },
        )
        .unwrap();
    }
}
