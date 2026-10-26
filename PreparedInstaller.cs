using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("Outfit Colours Prepared Installer")]
[assembly: AssemblyProduct("Outfit Colours Prepared Installer")]
[assembly: AssemblyCompany("")]
[assembly: AssemblyCopyright("")]
[assembly: AssemblyVersion("0.4.10.0")]

internal static class PreparedInstaller
{
    internal static string Assets { get { return Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Assets"); } }
    internal static string Manifest { get { return Path.Combine(Assets, "InstallManifest.json"); } }
    internal static string Script { get { return Path.Combine(Assets, "Install-Prepared.ps1"); } }
    internal static string Shell { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe"); } }

    [STAThread]
    private static int Main(string[] args)
    {
        try {
            if (args.Length == 1 && (args[0] == "--check" || args[0] == "--check-only")) {
                CheckBundle();
                Console.WriteLine("Installer manifest, payload paths and SHA256 hashes passed. No game files were changed.");
                return 0;
            }
            if(args.Length==3 && args[0]=="--game-root" && args[2]=="--install")return Install(args[1],Console.WriteLine);
            string chosen=null;
            if(args.Length==2 && args[0]=="--game-root")chosen=args[1];
            else if(args.Length!=0)throw new ArgumentException("Use --check-only, or --game-root <folder> with optional --install.");
            CheckBundle();
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm(chosen));
            return 0;
        } catch (Exception error) {
            if (args.Length > 0) Console.Error.WriteLine(error.Message);
            else MessageBox.Show(error.Message, "Prepared installer", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    internal static string CheckBundle()
    {
        AssertPlainPath(Assets);
        AssertPlainPath(Manifest);
        AssertPlainPath(Script);
        if (!File.Exists(Manifest) || !File.Exists(Script)) throw new FileNotFoundException("Installer files are missing. Extract the entire download and keep Assets beside InstallPrepared.exe.");
        if (!File.Exists(Shell)) throw new FileNotFoundException("Windows PowerShell is unavailable on this computer.");
        var serializer = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024, RecursionLimit = 100 };
        var data = serializer.DeserializeObject(File.ReadAllText(Manifest, Encoding.UTF8)) as Dictionary<string, object>;
        if(data==null||!data.ContainsKey("containerProfile")||Convert.ToString(data["containerProfile"])!="stellarblade-initial-single-export-v1")throw new InvalidDataException("Prepare outfits again with version 0.4.2 or newer before installing this output.");
        if (data == null || !data.ContainsKey("schemaVersion") || !(data["schemaVersion"] is int) || (int)data["schemaVersion"] != 1 || !data.ContainsKey("files")) throw new InvalidDataException("The install manifest is unsupported.");
        var rows = data["files"] as object[];
        if (rows == null) throw new InvalidDataException("Manifest files must be an array.");
        const string prefix = "SB/Binaries/Win64/ue4ss/Mods/DekCNS/Scripts/";
        var required = new HashSet<string>(new[] { prefix + "main.lua", prefix + "OutfitReversal/Init.lua", prefix + "OutfitReversal/MetadataBridge.lua", prefix + "OutfitReversal/Prepared.json" }, StringComparer.Ordinal);
        var allowed = new HashSet<string>(required, StringComparer.Ordinal) { prefix + "OutfitReversal/AccessoryLink.lua" };
        var package = new Regex(@"^SB/Content/Paks/~mods/OutfitReversalPrepared/(OutfitReversalPrepared_[0-9]{1,10}_P)\.(pak|ucas|utoc)$", RegexOptions.CultureInvariant);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var expectedFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { Path.GetFullPath(Manifest), Path.GetFullPath(Script) };
        var groups = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        foreach (object value in rows) {
            var row = value as Dictionary<string, object>;
            if (row == null || !row.ContainsKey("relativePath") || !row.ContainsKey("sha256")) throw new InvalidDataException("Invalid manifest entry.");
            var relative = row["relativePath"] as string;
            var digest = row["sha256"] as string;
            if (String.IsNullOrEmpty(relative) || relative.IndexOf('\\') >= 0 || relative.IndexOf(':') >= 0 || Path.IsPathRooted(relative)) throw new InvalidDataException("Manifest paths must be plain relative SB paths.");
            foreach (string part in relative.Split('/')) if (part == "" || part == "." || part == "..") throw new InvalidDataException("Invalid manifest path.");
            if (!seen.Add(relative)) throw new InvalidDataException("Duplicate manifest destination.");
            var match = package.Match(relative);
            if (!allowed.Contains(relative) && !match.Success) throw new InvalidDataException("Manifest contains an unsupported file.");
            if (digest == null || !Regex.IsMatch(digest, "\\A[0-9a-fA-F]{64}\\z")) throw new InvalidDataException("Manifest SHA256 is invalid.");
            var path = Path.GetFullPath(Path.Combine(Assets, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!path.StartsWith(Path.GetFullPath(Assets).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Manifest path escapes Assets.");
            AssertPlainPath(path);
            if (!File.Exists(path)) throw new FileNotFoundException("Prepared payload file is missing: " + relative);
            using (var algorithm = SHA256.Create()) using (var stream = File.OpenRead(path)) {
                var actual = BitConverter.ToString(algorithm.ComputeHash(stream)).Replace("-", "");
                if (!actual.Equals(digest, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Prepared payload checksum failed: " + relative);
            }
            expectedFiles.Add(path);
            if (match.Success) {
                HashSet<string> extensions;
                if (!groups.TryGetValue(match.Groups[1].Value, out extensions)) { extensions = new HashSet<string>(StringComparer.Ordinal); groups.Add(match.Groups[1].Value, extensions); }
                extensions.Add(match.Groups[2].Value);
            }
        }
        foreach (string path in required) if (!seen.Contains(path)) throw new InvalidDataException("A required CNS payload file is missing.");
        bool removeAll=data.ContainsKey("removeAllPrepared") && data["removeAllPrepared"] is bool && (bool)data["removeAllPrepared"];
        var metadata=serializer.DeserializeObject(File.ReadAllText(Path.Combine(Assets,(prefix+"OutfitReversal/Prepared.json").Replace('/',Path.DirectorySeparatorChar)),Encoding.UTF8)) as Dictionary<string,object>;
        var choices=metadata!=null && metadata.ContainsKey("outfits")?metadata["outfits"] as Dictionary<string,object>:null;
        bool emptyRemoval=removeAll && choices!=null && choices.Count==0 && metadata.ContainsKey("schemaVersion") && Convert.ToInt32(metadata["schemaVersion"])==1 && groups.Count==0;
        if((removeAll && !emptyRemoval) || (groups.Count==0 && !emptyRemoval)) throw new InvalidDataException("No prepared package triplet or validated empty uninstall is present.");
        foreach (var group in groups.Values) if (!group.SetEquals(new[] { "pak", "ucas", "utoc" })) throw new InvalidDataException("A prepared package triplet is incomplete.");
        AssertPayloadTree(Assets, expectedFiles);
        return "";
    }

    private static void AssertPlainPath(string path)
    {
        for (var current = new DirectoryInfo(Path.GetFullPath(path)); current != null; current = current.Parent) {
            if ((File.Exists(current.FullName) || Directory.Exists(current.FullName)) && (File.GetAttributes(current.FullName) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Links and junctions are not supported.");
        }
    }

    private static void AssertPayloadTree(string directory, HashSet<string> expected)
    {
        foreach (string entry in Directory.EnumerateFileSystemEntries(directory)) {
            var attributes = File.GetAttributes(entry);
            if ((attributes & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("Links and junctions are not supported.");
            if ((attributes & FileAttributes.Directory) != 0) AssertPayloadTree(entry, expected);
            else if (!expected.Contains(Path.GetFullPath(entry))) throw new InvalidDataException("Assets contains an unlisted payload file: " + Path.GetFileName(entry));
        }
    }

    private static string Quote(string value)
    {
        var text = new StringBuilder("\""); int slashes = 0;
        foreach (char c in value) {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { text.Append('\\', slashes * 2 + 1); text.Append('"'); }
            else { text.Append('\\', slashes); text.Append(c); }
            slashes = 0;
        }
        text.Append('\\', slashes * 2); return text.Append('"').ToString();
    }

    internal static int Install(string gameRoot, Action<string> log)
    {
        CheckBundle();
        if (String.IsNullOrWhiteSpace(gameRoot) || !Directory.Exists(Path.Combine(gameRoot, "SB", "Content", "Paks"))) throw new InvalidDataException("Choose the Stellar Blade folder containing SB/Content/Paks.");
        var start = new ProcessStartInfo {
            FileName = Shell,
            Arguments = "-NoProfile -ExecutionPolicy Bypass -File " + Quote(Script) + " -ManifestPath " + Quote(Manifest) + " -GameRoot " + Quote(Path.GetFullPath(gameRoot)),
            WorkingDirectory = Assets, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        using (var process = new Process { StartInfo = start }) {
            process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) log(e.Data); };
            process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) log(e.Data); };
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine(); process.WaitForExit(); return process.ExitCode;
        }
    }
    internal static string DefaultGameRoot(){
        try{string file=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"OutfitColoursPreparer","Settings.json");
            if(File.Exists(file)){var data=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(file));object paks;
                if(data.TryGetValue("pakRoot",out paks)&&Directory.Exists(Convert.ToString(paks)))return Directory.GetParent(Convert.ToString(paks)).Parent.Parent.FullName;}}
        catch{}
        return LocalSetup.FindGame();
    }
}

internal sealed class InstallerForm : Form
{
    private TextBox target = new TextBox();
    private TextBox log = new TextBox();
    private Button browse = new Button();
    private Button install = new Button();
    private Label status = new Label();
    private bool running;
    internal InstallerForm(string chosen=null)
    {
        Icon = AppIcon.Load();
        Text = "Outfit Colours â€” Install prepared outfits"; ClientSize = new Size(760, 440); MinimumSize = new Size(776, 479);
        var instructions = new Label { Left = 16, Top = 15, Width = 725, Height = 40, Text = "Close Stellar Blade. Choose its main folder, then click Install. Existing files are backed up; package conflicts are checked before replacement." };
        target.SetBounds(16, 62, 625, 24); target.Text = chosen??PreparedInstaller.DefaultGameRoot();
        browse.SetBounds(650, 60, 94, 27); browse.Text = "Browseâ€¦";
        browse.Click += delegate { using (var dialog = new FolderBrowserDialog { Description = "Choose the Stellar Blade folder containing SB", SelectedPath = target.Text }) { if (dialog.ShowDialog(this) == DialogResult.OK) target.Text = dialog.SelectedPath; } };
        install.SetBounds(16, 103, 125, 32); install.Text = "Install"; install.Click += BeginInstall;
        status.SetBounds(155, 111, 585, 25); status.Text = "Ready. Nothing has been installed.";
        log.SetBounds(16, 151, 728, 272); log.Multiline = true; log.ReadOnly = true; log.ScrollBars = ScrollBars.Vertical; log.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        Controls.AddRange(new Control[] { instructions, target, browse, install, status, log });
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if (running) { e.Cancel = true; MessageBox.Show(this, "Wait for installation or rollback to finish before closing."); } };
    }
    private void Append(string text) { if (IsHandleCreated) BeginInvoke((Action)(() => log.AppendText(text + Environment.NewLine))); }
    private async void BeginInstall(object sender, EventArgs e)
    {
        if (running) return;
        string folder = target.Text.Trim();
        running = true; install.Enabled = browse.Enabled = target.Enabled = false; status.ForeColor = Color.Black; status.Text = "Installing and checking packagesâ€¦";
        try {
            int exit = await Task.Run(() => PreparedInstaller.Install(folder, Append));
            if (exit != 0) throw new InvalidOperationException("Installation did not complete. See the details below; the installer attempts to restore files changed during a failed installation.");
            status.ForeColor = Color.DarkGreen; status.Text = "Installation complete. You can start the game.";
        } catch (Exception error) { status.ForeColor = Color.DarkRed; status.Text = "Installation failed. See details below."; Append(error.Message); }
        finally { running = false; install.Enabled = browse.Enabled = target.Enabled = true; }
    }
}

