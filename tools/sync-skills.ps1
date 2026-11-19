#Requires -Version 7.0
<#
.SYNOPSIS
    Mirror the manifest-listed academic skills from the source skill root to
    the harness target roots, byte-identical, without ever touching anything
    outside the manifest's skill directories.

.DESCRIPTION
    For each skill in tools/manifest.json, compares per-file SHA256 hashes
    between the source skill dir and each target skill dir. When they differ,
    mirrors the WHOLE skill dir (robocopy /MIR /XJ) -- strictly WITHIN that
    skill dir. Non-manifest entries in any root are never created, deleted or
    modified. Target roots themselves are never created: a missing root is
    reported as a failure (conservative).

    Default roots: source ~/.claude/skills -> ~/.codex/skills and
    ~/.gemini/config/skills. The agents root (~/.agents/skills, general-purpose
    skills) is only touched with -IncludeAgentsRoot.

.PARAMETER DryRun
    Print planned changes; perform zero disk writes.

.PARAMETER SelfTest
    Run the built-in fake-root scenario in a fresh temp dir (no real roots,
    no installed skills required). Prints SELFTEST PASS and exits 0 on
    success; prints failures and exits 1 otherwise.

.PARAMETER IncludeAgentsRoot
    Also sync the manifest's optional_targets (the agents skill root).

.PARAMETER ManifestPath
    Manifest JSON. Defaults to manifest.json next to this script.

.NOTES
    Exit codes: 0 = everything consistent or successfully synced (DryRun:
    plan computed); 1 = any failure (missing source skill, missing target
    root, linked target skill dir, mirror error, post-mirror verification
    mismatch, bad manifest).
    Idempotent: a consistent tree produces zero writes on re-run.
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SelfTest,
    [switch]$IncludeAgentsRoot,
    [string]$ManifestPath = (Join-Path $PSScriptRoot 'manifest.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }

# ---------------------------------------------------------------- helpers

function Expand-RootPath {
    param([string]$Path)
    $p = $Path
    if ($p -eq '~') { $p = $HOME }
    elseif ($p.StartsWith('~/') -or $p.StartsWith('~\')) {
        $p = Join-Path $HOME $p.Substring(2)
    }
    return [System.IO.Path]::GetFullPath($p)
}

function Read-Manifest {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "manifest not found: $Path"
    }
    $m = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
    if ($null -eq $m) { throw "manifest is empty: $Path" }
    foreach ($key in 'source', 'targets', 'skills') {
        if (-not $m.ContainsKey($key)) { throw "manifest missing key '$key': $Path" }
    }
    if ([string]::IsNullOrWhiteSpace([string]$m['source'])) {
        throw 'manifest source must be a non-empty path'
    }
    if (@($m['targets']).Count -lt 1) { throw 'manifest targets must list at least one root' }
    foreach ($t in @($m['targets'])) {
        if ([string]::IsNullOrWhiteSpace([string]$t)) { throw 'manifest targets contains an empty path' }
    }
    if (-not $m.ContainsKey('optional_targets')) { $m['optional_targets'] = @() }
    foreach ($t in @($m['optional_targets'])) {
        if ([string]::IsNullOrWhiteSpace([string]$t)) { throw 'manifest optional_targets contains an empty path' }
    }
    if (@($m['skills']).Count -lt 1) { throw 'manifest skills must list at least one skill' }
    $seen = @{}
    foreach ($s in @($m['skills'])) {
        if ($s -isnot [System.Collections.IDictionary]) { throw 'manifest skill entry must be an object' }
        if (-not $s.ContainsKey('name') -or -not $s.ContainsKey('category')) {
            throw 'manifest skill entry needs both name and category'
        }
        $name = [string]$s['name']
        # Safety valve: a skill name must be a single plain directory name,
        # so a manifest can never point outside the roots (no .., no slashes).
        if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
            throw "unsafe skill name in manifest: '$name'"
        }
        if ($seen.ContainsKey($name)) { throw "duplicate skill in manifest: $name" }
        $seen[$name] = $true
        if (@('writing', 'research-tool', 'general') -notcontains [string]$s['category']) {
            throw "unknown category for skill '$name': '$([string]$s['category'])'"
        }
    }
    return $m
}

# relpath -> SHA256 for every file under a skill dir; $null if dir missing.
function Get-SkillFileMap {
    param([string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return $null }
    $full = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
    $map = @{}
    foreach ($f in @(Get-ChildItem -LiteralPath $full -Recurse -File -Force)) {
        $rel = $f.FullName.Substring($full.Length + 1).Replace('\', '/')
        $map[$rel] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
    }
    return $map
}

# relpath -> "size|mtimeTicks|sha256" for files, "DIR" for subdirectories.
function Get-TreeSnapshot {
    param([string]$Root)
    $full = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
    $map = @{}
    foreach ($d in @(Get-ChildItem -LiteralPath $full -Recurse -Directory -Force)) {
        $rel = $d.FullName.Substring($full.Length + 1).Replace('\', '/')
        $map[$rel] = 'DIR'
    }
    foreach ($f in @(Get-ChildItem -LiteralPath $full -Recurse -File -Force)) {
        $rel = $f.FullName.Substring($full.Length + 1).Replace('\', '/')
        $map[$rel] = '{0}|{1}|{2}' -f $f.Length, $f.LastWriteTimeUtc.Ticks,
            (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
    }
    return $map
}

function Compare-StringMap {
    param([System.Collections.IDictionary]$A, [System.Collections.IDictionary]$B)
    $diffs = [System.Collections.Generic.List[string]]::new()
    foreach ($k in $A.Keys) {
        if (-not $B.ContainsKey($k)) { $diffs.Add("only-in-A: $k") }
        elseif ($A[$k] -ne $B[$k]) { $diffs.Add("value-mismatch: $k") }
    }
    foreach ($k in $B.Keys) {
        if (-not $A.ContainsKey($k)) { $diffs.Add("only-in-B: $k") }
    }
    return , $diffs
}

function Get-SkillDiff {
    param([System.Collections.IDictionary]$SrcMap, [System.Collections.IDictionary]$DstMap)
    $added = [System.Collections.Generic.List[string]]::new()
    $modified = [System.Collections.Generic.List[string]]::new()
    $removed = [System.Collections.Generic.List[string]]::new()
    foreach ($k in $SrcMap.Keys) {
        if ($null -eq $DstMap -or -not $DstMap.ContainsKey($k)) { $added.Add($k) }
        elseif ($SrcMap[$k] -ne $DstMap[$k]) { $modified.Add($k) }
    }
    if ($null -ne $DstMap) {
        foreach ($k in $DstMap.Keys) {
            if (-not $SrcMap.ContainsKey($k)) { $removed.Add($k) }
        }
    }
    $different = ($null -eq $DstMap) -or (($added.Count + $modified.Count + $removed.Count) -gt 0)
    return [pscustomobject]@{
        Added = $added; Modified = $modified; Removed = $removed; IsDifferent = $different
    }
}

# ---------------------------------------------------------------- core

function Invoke-Sync {
    param(
        [System.Collections.IDictionary]$Manifest,
        [switch]$IncludeAgentsRoot,
        [switch]$DryRun
    )
    $consistent = 0; $synced = 0; $planned = 0; $failed = 0
    $sourceRoot = Expand-RootPath -Path ([string]$Manifest['source'])
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
        Write-Host "FATAL: source root does not exist: $sourceRoot"
        return 1
    }
    $rootSpecs = @($Manifest['targets'])
    if ($IncludeAgentsRoot) { $rootSpecs += @($Manifest['optional_targets']) }
    foreach ($spec in $rootSpecs) {
        $targetRoot = Expand-RootPath -Path ([string]$spec)
        if (-not (Test-Path -LiteralPath $targetRoot -PathType Container)) {
            Write-Host "[$targetRoot] FAILED: target root does not exist (refusing to create it)"
            $failed++
            continue
        }
        foreach ($skill in @($Manifest['skills'])) {
            $name = [string]$skill['name']
            $srcDir = Join-Path $sourceRoot $name
            $dstDir = Join-Path $targetRoot $name
            # Write-scope escape guard (fix-wave F13): a target skill dir that
            # is itself a junction/symlink would let /MIR write THROUGH the
            # link to wherever it points (outside the root). Refuse before
            # any read or mirror of the target; /XJ only skips junctions
            # encountered INSIDE the tree, not a linked destination root.
            $dstItem = Get-Item -LiteralPath $dstDir -Force -ErrorAction SilentlyContinue
            if ($null -ne $dstItem -and $null -ne $dstItem.LinkType) {
                Write-Host "[$targetRoot] ${name}: FAILED (target skill dir is a $($dstItem.LinkType); refusing to mirror through a link)"
                $failed++
                continue
            }
            $srcMap = Get-SkillFileMap -Root $srcDir
            if ($null -eq $srcMap) {
                Write-Host "[$targetRoot] ${name}: FAILED (skill missing in source: $srcDir)"
                $failed++
                continue
            }
            $dstMap = Get-SkillFileMap -Root $dstDir
            $diff = Get-SkillDiff -SrcMap $srcMap -DstMap $dstMap
            if (-not $diff.IsDifferent) {
                Write-Host "[$targetRoot] ${name}: CONSISTENT ($($srcMap.Count) files)"
                $consistent++
                continue
            }
            $detail = "+$($diff.Added.Count) ~$($diff.Modified.Count) -$($diff.Removed.Count)"
            if ($DryRun) {
                $reason = if ($null -eq $dstMap) { 'target skill dir missing' } else { 'content drift' }
                Write-Host "[$targetRoot] ${name}: DRYRUN would mirror ($detail; $reason)"
                $planned++
                continue
            }
            # Mirror strictly WITHIN this manifest skill dir. /XJ skips
            # junctions so nothing outside the dir is followed or copied.
            $roboArgs = @(
                $srcDir.TrimEnd('\'), $dstDir.TrimEnd('\'),
                '/MIR', '/XJ', '/R:2', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
            )
            $roboOut = & robocopy.exe @roboArgs 2>&1
            $roboExit = $LASTEXITCODE
            if ($roboExit -ge 8) {
                Write-Host "[$targetRoot] ${name}: FAILED (robocopy exit $roboExit)"
                foreach ($line in $roboOut) { Write-Host "    $line" }
                $failed++
                continue
            }
            $verifyMap = Get-SkillFileMap -Root $dstDir
            if ($null -eq $verifyMap) {
                Write-Host "[$targetRoot] ${name}: FAILED (post-mirror verification: dir missing)"
                $failed++
                continue
            }
            $verifyDiff = Compare-StringMap -A $srcMap -B $verifyMap
            if ($verifyDiff.Count -gt 0) {
                Write-Host "[$targetRoot] ${name}: FAILED (post-mirror verification mismatch)"
                foreach ($d in $verifyDiff) { Write-Host "    $d" }
                $failed++
                continue
            }
            Write-Host "[$targetRoot] ${name}: SYNCED ($detail; verified $($srcMap.Count) files)"
            $synced++
        }
    }
    $mode = if ($DryRun) { 'dry-run' } else { 'sync' }
    Write-Host "Summary ($mode): consistent=$consistent synced=$synced planned=$planned failed=$failed"
    if ($failed -gt 0) { return 1 }
    return 0
}

# ---------------------------------------------------------------- selftest

$script:StFailures = [System.Collections.Generic.List[string]]::new()

function Assert-ST {
    param([bool]$Condition, [string]$Label)
    if ($Condition) { Write-Host "  [ok] $Label" }
    else { Write-Host "  [FAIL] $Label"; $script:StFailures.Add($Label) }
}

function New-TestFile {
    param([string]$Path, [string]$Content)
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    [System.IO.File]::WriteAllText($Path, $Content)
}

function Test-SkillAligned {
    param([string]$SrcDir, [string]$DstDir)
    $a = Get-SkillFileMap -Root $SrcDir
    $b = Get-SkillFileMap -Root $DstDir
    if ($null -eq $a -or $null -eq $b) { return $false }
    return ((Compare-StringMap -A $a -B $b).Count -eq 0)
}

function Get-RootSnapshots {
    param([string[]]$Roots)
    $h = @{}
    foreach ($r in $Roots) { $h[$r] = Get-TreeSnapshot -Root $r }
    return $h
}

function Test-SnapshotsUnchanged {
    param([System.Collections.IDictionary]$Before, [System.Collections.IDictionary]$After)
    foreach ($r in $Before.Keys) {
        if ((Compare-StringMap -A $Before[$r] -B $After[$r]).Count -gt 0) { return $false }
    }
    return $true
}

function Invoke-SelfTest {
    $base = Join-Path ([System.IO.Path]::GetTempPath()) ('sync-skills-selftest-' + [guid]::NewGuid().ToString('N'))
    Write-Host "SelfTest fake roots: $base"
    try {
        $src = Join-Path $base 'source'
        $t1 = Join-Path $base 'target1'
        $t2 = Join-Path $base 'target2'
        $t3 = Join-Path $base 'target3-agents'
        $allRoots = @($src, $t1, $t2, $t3)

        # Fixtures: skillA has 2 files (one nested); skillB is aligned everywhere.
        New-TestFile -Path (Join-Path $src 'skillA/SKILL.md') -Content "skillA main v2`n"
        New-TestFile -Path (Join-Path $src 'skillA/refs/deep.md') -Content "skillA reference v2`n"
        New-TestFile -Path (Join-Path $src 'skillB/SKILL.md') -Content "skillB v1`n"
        # target1: skillA missing entirely; skillB aligned.
        New-TestFile -Path (Join-Path $t1 'skillB/SKILL.md') -Content "skillB v1`n"
        # target2: skillA stale-modified + one aligned file + one extra junk file;
        # plus a NON-manifest dir that must survive mirroring.
        New-TestFile -Path (Join-Path $t2 'skillA/SKILL.md') -Content "skillA main STALE`n"
        New-TestFile -Path (Join-Path $t2 'skillA/refs/deep.md') -Content "skillA reference v2`n"
        New-TestFile -Path (Join-Path $t2 'skillA/junk-extra.txt') -Content "extra file mirroring must remove`n"
        New-TestFile -Path (Join-Path $t2 'outsider-t2/keep.txt') -Content "non-manifest skill; hands off`n"
        # target3 (agents-like): stale skillA + outsider skillX.
        New-TestFile -Path (Join-Path $t3 'skillA/SKILL.md') -Content "skillA main STALE-AGENTS`n"
        New-TestFile -Path (Join-Path $t3 'skillX/secret.txt') -Content "outsider general-purpose skill; never touch`n"

        $fakeManifestPath = Join-Path $base 'fake-manifest.json'
        @{
            source           = $src
            targets          = @($t1, $t2)
            optional_targets = @($t3)
            skills           = @(
                @{ name = 'skillA'; category = 'general' },
                @{ name = 'skillB'; category = 'general' }
            )
        } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $fakeManifestPath -Encoding UTF8
        $fm = Read-Manifest -Path $fakeManifestPath

        Write-Host 'Phase 1: -DryRun default (zero disk writes)'
        $before = Get-RootSnapshots -Roots $allRoots
        $rc = Invoke-Sync -Manifest $fm -DryRun
        Assert-ST ($rc -eq 0) 'dry-run default exits 0'
        Assert-ST (Test-SnapshotsUnchanged -Before $before -After (Get-RootSnapshots -Roots $allRoots)) 'dry-run default wrote nothing'

        Write-Host 'Phase 2: -DryRun -IncludeAgentsRoot (zero disk writes)'
        $rc = Invoke-Sync -Manifest $fm -DryRun -IncludeAgentsRoot
        Assert-ST ($rc -eq 0) 'dry-run opt-in exits 0'
        Assert-ST (Test-SnapshotsUnchanged -Before $before -After (Get-RootSnapshots -Roots $allRoots)) 'dry-run opt-in wrote nothing'

        Write-Host 'Phase 3: default run (agents root must stay untouched)'
        $rc = Invoke-Sync -Manifest $fm
        Assert-ST ($rc -eq 0) 'default run exits 0'
        Assert-ST (Test-SkillAligned -SrcDir (Join-Path $src 'skillA') -DstDir (Join-Path $t1 'skillA')) 'target1 gained aligned skillA'
        Assert-ST (Test-SkillAligned -SrcDir (Join-Path $src 'skillA') -DstDir (Join-Path $t2 'skillA')) 'target2 skillA aligned'
        Assert-ST (-not (Test-Path -LiteralPath (Join-Path $t2 'skillA/junk-extra.txt'))) 'mirror removed extra file INSIDE skillA only'
        $outsiderBefore = @{ 'keep.txt' = $before[$t2]['outsider-t2/keep.txt'] }
        $outsiderAfter = @{ 'keep.txt' = (Get-TreeSnapshot -Root $t2)['outsider-t2/keep.txt'] }
        Assert-ST ((Compare-StringMap -A $outsiderBefore -B $outsiderAfter).Count -eq 0) 'non-manifest dir in target2 survived byte+mtime identical'
        Assert-ST ((Compare-StringMap -A $before[$t3] -B (Get-TreeSnapshot -Root $t3)).Count -eq 0) 'agents-like target3 untouched entirely by default'
        Assert-ST (Test-SkillAligned -SrcDir (Join-Path $src 'skillB') -DstDir (Join-Path $t1 'skillB')) 'skillB still aligned in target1'
        Assert-ST ((Compare-StringMap -A $before[$src] -B (Get-TreeSnapshot -Root $src)).Count -eq 0) 'source root never modified'

        Write-Host 'Phase 4: idempotent re-run (consistent tree, zero writes)'
        $beforeRerun = Get-RootSnapshots -Roots $allRoots
        $rc = Invoke-Sync -Manifest $fm
        Assert-ST ($rc -eq 0) 're-run exits 0'
        Assert-ST (Test-SnapshotsUnchanged -Before $beforeRerun -After (Get-RootSnapshots -Roots $allRoots)) 're-run wrote nothing'

        Write-Host 'Phase 5: -IncludeAgentsRoot (skillX must stay untouched)'
        $skillXBefore = Get-TreeSnapshot -Root (Join-Path $t3 'skillX')
        $rc = Invoke-Sync -Manifest $fm -IncludeAgentsRoot
        Assert-ST ($rc -eq 0) 'opt-in run exits 0'
        Assert-ST (Test-SkillAligned -SrcDir (Join-Path $src 'skillA') -DstDir (Join-Path $t3 'skillA')) 'target3 gained aligned skillA'
        Assert-ST ((Compare-StringMap -A $skillXBefore -B (Get-TreeSnapshot -Root (Join-Path $t3 'skillX'))).Count -eq 0) 'outsider skillX untouched'
        Assert-ST ((Compare-StringMap -A $beforeRerun[$t1] -B (Get-TreeSnapshot -Root $t1)).Count -eq 0) 'target1 unchanged by opt-in run'
        Assert-ST ((Compare-StringMap -A $beforeRerun[$t2] -B (Get-TreeSnapshot -Root $t2)).Count -eq 0) 'target2 unchanged by opt-in run'

        Write-Host 'Phase 6: missing source skill must fail (exit 1)'
        Remove-Item -LiteralPath (Join-Path $src 'skillB') -Recurse -Force
        $rc = Invoke-Sync -Manifest $fm
        Assert-ST ($rc -eq 1) 'missing source skill exits 1'

        Write-Host 'Phase 7: missing target root must fail and NOT be created'
        $ghost = Join-Path $base 'ghost-root'
        $ghostManifestPath = Join-Path $base 'ghost-manifest.json'
        @{
            source  = $src
            targets = @($ghost)
            skills  = @(@{ name = 'skillA'; category = 'general' })
        } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ghostManifestPath -Encoding UTF8
        $gm = Read-Manifest -Path $ghostManifestPath
        $rc = Invoke-Sync -Manifest $gm
        Assert-ST ($rc -eq 1) 'missing target root exits 1'
        Assert-ST (-not (Test-Path -LiteralPath $ghost)) 'missing target root was not created'

        Write-Host 'Phase 8: junction target skill dir must be refused (no write-through)'
        # Restore source skillB (removed in Phase 6) so the ONLY failure below
        # is the junction itself, not a missing source skill.
        New-TestFile -Path (Join-Path $src 'skillB/SKILL.md') -Content "skillB v1`n"
        $elsewhere = Join-Path $base 'elsewhere'
        New-TestFile -Path (Join-Path $elsewhere 'sentinel.txt') -Content "outside the skill dir; must never be written through`n"
        $junction = Join-Path $t1 'skillB'
        Remove-Item -LiteralPath $junction -Recurse -Force -Confirm:$false
        New-Item -ItemType Junction -Path $junction -Target $elsewhere | Out-Null
        $elsewhereBefore = Get-TreeSnapshot -Root $elsewhere
        $captured = @(Invoke-Sync -Manifest $fm 6>&1)
        $rc = @($captured | Where-Object { $_ -is [int] })[-1]
        $syncText = ($captured | ForEach-Object { "$_" }) -join "`n"
        Assert-ST ($rc -eq 1) 'junction target skill dir exits 1'
        Assert-ST ($syncText -match 'refusing to mirror through a link') 'refusal explicitly names the link'
        Assert-ST ((Compare-StringMap -A $elsewhereBefore -B (Get-TreeSnapshot -Root $elsewhere)).Count -eq 0) 'junction target not written through'
        Assert-ST (-not (Test-Path -LiteralPath (Join-Path $elsewhere 'SKILL.md'))) 'no SKILL.md appeared behind the junction'
        Assert-ST ($null -ne (Get-Item -LiteralPath $junction -Force).LinkType) 'junction left in place (not followed, not deleted)'
        # Delete the junction LINK only (DirectoryInfo.Delete on a reparse
        # point never recurses into the target), then sync must succeed.
        (Get-Item -LiteralPath $junction -Force).Delete()
        $rc = Invoke-Sync -Manifest $fm
        Assert-ST ($rc -eq 0) 'after junction removal sync exits 0'
        Assert-ST (Test-SkillAligned -SrcDir (Join-Path $src 'skillB') -DstDir $junction) 'skillB mirrored normally after junction removal'
        Assert-ST ((Compare-StringMap -A $elsewhereBefore -B (Get-TreeSnapshot -Root $elsewhere)).Count -eq 0) 'elsewhere still untouched after real mirror'
    }
    finally {
        if (Test-Path -LiteralPath $base -PathType Container) {
            Remove-Item -LiteralPath $base -Recurse -Force
        }
    }
    if ($script:StFailures.Count -eq 0) {
        Write-Host 'SELFTEST PASS'
        return 0
    }
    Write-Host "SELFTEST FAIL ($($script:StFailures.Count) assertion(s): $($script:StFailures -join '; '))"
    return 1
}

# ---------------------------------------------------------------- main

try {
    if ($SelfTest) { exit (Invoke-SelfTest) }
    $manifest = Read-Manifest -Path $ManifestPath
    exit (Invoke-Sync -Manifest $manifest -IncludeAgentsRoot:$IncludeAgentsRoot -DryRun:$DryRun)
}
catch {
    Write-Host "FATAL: $($_.Exception.Message)"
    exit 1
}