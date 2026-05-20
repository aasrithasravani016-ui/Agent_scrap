-- Switch specifications database schema
-- Single normalized table works fine for v1 (~500-1000 models)

CREATE TABLE IF NOT EXISTS switches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identification
    vendor TEXT NOT NULL,
    family TEXT,
    model TEXT NOT NULL,
    sku TEXT,

    -- Port configuration
    port_count INTEGER,
    port_speed_max_gbps INTEGER,
    port_config TEXT,         -- human-readable: "48x 1G + 4x SFP+"
    uplink_config TEXT,

    -- Performance
    switching_capacity_gbps REAL,
    forwarding_rate_mpps REAL,
    buffer_mb REAL,
    latency_ns INTEGER,

    -- Tables
    mac_table_size INTEGER,

    -- Power and PoE
    poe_standard TEXT,        -- PoE / PoE+ / PoE++ / UPOE+ / None
    poe_budget_w INTEGER,
    power_typical_w INTEGER,
    power_max_w INTEGER,

    -- Features
    layer TEXT,               -- L2 / L2+ / L3
    features TEXT,            -- JSON array

    -- Physical
    rack_units INTEGER,

    -- Software
    nos TEXT,                 -- IOS-XE / EOS / Junos / ArubaOS-CX / RouterOS / UniFi / Omada / Cumulus / SONiC

    -- Lifecycle
    status TEXT,              -- active / EoS / EoL

    -- Use case
    use_case TEXT,            -- access / aggregation / core / spine / leaf / ToR

    -- Source
    datasheet_url TEXT,
    image_url TEXT,           -- product image URL (linked, not stored bytes)
    extra_specs TEXT,         -- JSON dict of additional datasheet fields not in the schema
    last_updated TEXT
);

CREATE INDEX IF NOT EXISTS idx_vendor ON switches(vendor);
CREATE INDEX IF NOT EXISTS idx_model ON switches(model);
CREATE INDEX IF NOT EXISTS idx_sku ON switches(sku);
CREATE INDEX IF NOT EXISTS idx_family ON switches(family);


-- Firmware version registry
-- One row per published firmware release for a vendor's NOS.
-- Keyed by (vendor, nos, version).
CREATE TABLE IF NOT EXISTS firmware_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    vendor TEXT NOT NULL,            -- Cisco, Arista, MikroTik, etc.
    nos TEXT NOT NULL,               -- IOS-XE / EOS / Junos / RouterOS / UniFi / Cumulus / Omada
    version TEXT NOT NULL,           -- "7.18.2" / "17.12.4" / "4.31.2F" / etc

    -- Release info
    release_date TEXT,               -- ISO date if known
    train TEXT,                      -- stable / LTS / beta / suggested / deferred
    is_recommended INTEGER,          -- 1 if vendor explicitly marks "recommended"

    -- Compatibility - which switch models this firmware runs on.
    -- JSON array of model strings, or NULL = applies to whole vendor NOS line.
    applies_to_models TEXT,

    -- Content of the release notes / changelog (per-version)
    new_features TEXT,               -- JSON array of strings
    security_fixes TEXT,             -- JSON array of strings (CVE IDs preferred)
    bug_fixes TEXT,                  -- JSON array of strings
    known_issues TEXT,               -- JSON array of strings
    deprecations TEXT,               -- JSON array of strings

    -- Source
    release_notes_url TEXT,
    source TEXT,                     -- where this data came from
    last_updated TEXT,

    UNIQUE(vendor, nos, version)
);

CREATE INDEX IF NOT EXISTS idx_fw_vendor_nos ON firmware_versions(vendor, nos);
CREATE INDEX IF NOT EXISTS idx_fw_version ON firmware_versions(version);
CREATE INDEX IF NOT EXISTS idx_fw_date ON firmware_versions(release_date);


-- Security advisories (CVEs) keyed by (cve_id, vendor).
-- Populated from public sources (NIST NVD). Decoupled from firmware_versions
-- so we can surface vulnerability data even when full release notes are
-- behind a vendor login wall.
CREATE TABLE IF NOT EXISTS security_advisories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    cve_id TEXT NOT NULL,            -- e.g. CVE-2022-23679
    vendor TEXT NOT NULL,            -- 'HPE Aruba' / 'Cisco' / ...
    nos TEXT,                        -- 'AOS-CX' / 'IOS-XE' / 'Junos' / ...

    published TEXT,                  -- ISO date (NVD publishedDate)
    last_modified TEXT,              -- ISO date (NVD lastModifiedDate)
    severity TEXT,                   -- CRITICAL / HIGH / MEDIUM / LOW
    cvss_score REAL,                 -- CVSS v3.1 base score (preferred), else v3.0/v2
    cvss_vector TEXT,
    description TEXT,                -- English description

    -- JSON array of {product, start, start_incl, end, end_incl} ranges
    -- Each range describes a contiguous block of affected versions.
    affected_ranges TEXT,

    -- JSON array of version strings derived from each range's upper bound
    -- (the first known *fixed* version)
    fixed_versions TEXT,

    references_json TEXT,            -- JSON array of {url, source}
    source TEXT,                     -- 'nvd' / 'cisco-psirt' / etc.
    last_updated TEXT,

    -- CISA "Known Exploited Vulnerabilities" overlay. When True, this
    -- CVE is on the U.S. government's official list of vulnerabilities
    -- that attackers are CURRENTLY using in the wild. Hugely important
    -- for prioritization — most CVEs are theoretical, KEV ones aren't.
    actively_exploited INTEGER DEFAULT 0,
    kev_date_added TEXT,             -- ISO date CISA added it to the catalog
    kev_due_date TEXT,               -- ISO date federal agencies must patch by
    kev_required_action TEXT,        -- CISA's required mitigation text

    UNIQUE(cve_id, vendor)
);

CREATE INDEX IF NOT EXISTS idx_adv_vendor_nos ON security_advisories(vendor, nos);
CREATE INDEX IF NOT EXISTS idx_adv_cve ON security_advisories(cve_id);
CREATE INDEX IF NOT EXISTS idx_adv_severity ON security_advisories(severity);
