rule Detect_Malicious_URL {
    meta:
        description = "Identifies specific malicious URL patterns"
        author = "rbdebeer"

    strings:
        $url = "http://malicious-site.com"
        $path = "/payload"

    condition:
        $url and $path
}