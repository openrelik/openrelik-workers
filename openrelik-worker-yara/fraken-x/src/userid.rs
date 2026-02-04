use std::{
    collections::HashMap,
    fs::File,
    io::{BufRead, BufReader},
};

pub fn get_usernames_from_passwd(
    file_path: &str,
) -> Result<HashMap<u32, String>, Box<dyn std::error::Error>> {
    let file = File::open(file_path)?;
    let reader = BufReader::new(file);
    let mut users = HashMap::new();

    for line in reader.lines() {
        let line = line?;
        let parts: Vec<&str> = line.split(':').collect();
        if parts.len() >= 3 {
            // Ensure at least username, password, and UID exist
            let uid = parts[2].parse::<u32>()?;
            users.insert(uid, parts[0].to_string());
        }
    }
    Ok(users)
}
