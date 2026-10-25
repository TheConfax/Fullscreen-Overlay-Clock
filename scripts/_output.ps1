# Console output shared by the dev scripts: the same layout and colors as _output.py.

$Esc = [char]27
$Column = 5
$StepTotal = 0
$StepCount = 0

function Paint([string]$Text, [string]$Codes) {
    if ($Codes) { "$Esc[$($Codes)m$Text$Esc[0m" } else { $Text }
}

function Steps([int]$Total, [string]$Title) {
    $script:StepTotal = $Total
    Write-Host (Paint "$Title..." "1;36")
}

function Step([string]$Text) {
    if ($script:StepCount) { Write-Host "" }
    $script:StepCount++
    if ($script:StepTotal -gt 1) {
        Write-Host (Paint "[$($script:StepCount)/$($script:StepTotal)] $Text..." "36")
    } else {
        Write-Host (Paint "$Text..." "1;36")
    }
}

function Line([string]$Word, [string]$Codes, [string]$Text) {
    Write-Host ((Paint $Word $Codes) + (" " * ($Column - $Word.Length)) + $Text)
}

function Ok([string]$Text) { Line "OK" "32" $Text }
function Fail([string]$Text) { Line "FAIL" "31" $Text }
function Fix([string]$Text) { Line "FIX" "36" $Text }
function Info([string]$Text) { Line "INFO" "" $Text }

function Fatal([string]$Text, [string]$Remedy) {
    Fail $Text
    if ($Remedy) { Fix $Remedy }
    exit 1
}
