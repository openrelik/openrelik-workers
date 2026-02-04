use std::{
    fs::File,
    io::{BufRead, BufReader, Read},
};

// Trait to abstract over different Read types
pub trait Readable: BufRead {}

impl<T: Read> Readable for BufReader<T> {}

pub fn parse_definitions_file<R: Readable>(
    reader: R,
) -> Result<(Vec<(Vec<u8>, String)>, usize), Box<dyn std::error::Error>> {
    let mut definitions = Vec::new();
    let mut max_len = 0;

    for line in std::io::BufRead::lines(reader) {
        let line = line?;
        let line = line.trim();

        if line.is_empty() || line.starts_with('#') {
            continue;
        }

        let parts: Vec<&str> = line.split(';').collect();
        if parts.len() != 2 {
            return Err(format!("Invalid line format: {}", line).into());
        }

        let hex_str = parts[0].trim();
        let description = parts[1].trim().to_string();

        let hex_bytes = hex_str
            .split_whitespace()
            .map(|byte_str| u8::from_str_radix(byte_str, 16))
            .collect::<Result<Vec<u8>, _>>()?;

        let len = hex_bytes.len();
        if len > max_len {
            max_len = len;
        }

        definitions.push((hex_bytes, description));
    }

    Ok((definitions, max_len))
}

pub fn read_first_bytes(
    file_path: &str,
    num_bytes: usize,
) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    if file_path.is_empty() {
        return Ok(Vec::new());
    }
    let file = File::open(file_path)?;
    let reader = BufReader::new(file);
    let mut buffer = Vec::new();
    reader.take(num_bytes as u64).read_to_end(&mut buffer)?;

    Ok(buffer)
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use super::*;

    #[test]
    fn test_parse_definitions_file_valid() -> Result<(), Box<dyn std::error::Error>> {
        let test_file_content = "# Comments\nCA FE;Java Class\n5B 30 30;MimiLSA\n";
        let reader = BufReader::new(Cursor::new(test_file_content.as_bytes()));

        let (definitions, max_len) = parse_definitions_file(reader)?;

        assert_eq!(definitions.len(), 2);
        assert_eq!(max_len, 3); // Check max length

        Ok(())
    }

    #[test]
    fn test_parse_definitions_file_empty() -> Result<(), Box<dyn std::error::Error>> {
        let test_file_content = "";
        let reader = BufReader::new(Cursor::new(test_file_content.as_bytes()));

        let (definitions, _) = parse_definitions_file(reader)?;
        assert_eq!(definitions.len(), 0);

        Ok(())
    }

    #[test]
    fn test_parse_definitions_file_comments_only() -> Result<(), Box<dyn std::error::Error>> {
        let test_file_content = "# Comment 1\n# Comment 2";
        let reader = BufReader::new(Cursor::new(test_file_content.as_bytes()));

        let (definitions, _) = parse_definitions_file(reader)?;
        assert_eq!(definitions.len(), 0);

        Ok(())
    }

    #[test]
    fn test_parse_definitions_file_invalid_format() -> Result<(), Box<dyn std::error::Error>> {
        let test_file_content = "CA FE Java Class"; // Missing semicolon
        let reader = BufReader::new(Cursor::new(test_file_content.as_bytes()));

        let result = parse_definitions_file(reader);
        assert!(result.is_err());

        Ok(())
    }

    #[test]
    fn test_parse_definitions_file_invalid_hex() -> Result<(), Box<dyn std::error::Error>> {
        let test_file_content = "CA FG;Java Class"; // Invalid hex value
        let reader = BufReader::new(Cursor::new(test_file_content.as_bytes()));

        let result = parse_definitions_file(reader);
        assert!(result.is_err());

        Ok(())
    }
}
