rule Detect_Project_Alpha {
    meta:
        description = "Detects files associated with Project Alpha"
        author = "rbdebeer"
    
    strings:
        $project_name = "Project-Alpha" nocase
        $key_format = /AX[0-9]{2}-[A-Z][0-9]{2}-[A-Z]/ 

    condition:
        $project_name or $key_format
}