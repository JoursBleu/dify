using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Xml.Linq;

[assembly: AssemblyTitle("Dify Local Windows Installer")]
[assembly: AssemblyDescription("Dify 1.17.1 local integration by Letian Kang; contact: Letian.Kang@amd.com")]
[assembly: AssemblyCompany("Letian Kang")]
[assembly: AssemblyMetadata("Author", "Letian Kang")]
[assembly: AssemblyMetadata("Contact", "Letian.Kang@amd.com")]
[assembly: AssemblyVersion("1.0.8.0")]
[assembly: AssemblyFileVersion("1.0.8.0")]

internal static class Program
{
    internal static readonly string Home = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Programs", "DifyLocal");
    internal static readonly string Payload = Path.Combine(Home, "payload");
    internal static readonly string InstalledExe = Path.Combine(Home, "Dify.exe");
    internal static readonly string SettingsPath = Path.Combine(Home, "settings.xml");
    internal static readonly string Wsl = Path.Combine(Environment.GetFolderPath(
        Environment.SpecialFolder.Windows), "System32", "wsl.exe");
    internal const string IntegrationAttribution = "集成作者：Letian Kang · 联系邮箱：Letian.Kang@amd.com";

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (IsSelfTestRequest(args))
            {
                if (args[0] == "--wsl-self-test") WslSelfTest(args[1]);
                else if (args[0] == "--http-self-test")
                    HttpSelfTest(args[1], args.Length == 3 ? Int32.Parse(args[2]) : 18080);
                else SelfTest(args[1]);
                return 0;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            using (var instance = new System.Threading.Mutex(false, "Local\\DifyLocalInstaller"))
            {
                if (!instance.WaitOne(0))
                {
                    MessageBox.Show("Dify 安装与管理窗口已经打开。", "Dify");
                    return 1;
                }
                try { Application.Run(new InstallerForm(args.FirstOrDefault())); }
                finally { instance.ReleaseMutex(); }
            }
            return 0;
        }
        catch (Exception error)
        {
            if (IsSelfTestRequest(args))
                File.WriteAllText(args[1], "FAIL: " + error.Message, Encoding.UTF8);
            else
                MessageBox.Show(error.Message, "Dify 安装器", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static bool IsSelfTestRequest(string[] args)
    {
        return args.Length >= 2 && args.Length <= 3
            && (args[0] == "--self-test" || args[0] == "--wsl-self-test"
                || args[0] == "--http-self-test");
    }

    internal static string LocalOrigin(int port)
    {
        if (port < 1024 || port > 65535)
            throw new InvalidOperationException("Invalid local Dify port.");
        // Docker publishes IPv4 loopback. .NET may resolve localhost to ::1 without IPv4 fallback.
        return "http://127.0.0.1:" + port;
    }

    internal static string IntegrationsUrl(int port)
    {
        return LocalOrigin(port) + "/integrations";
    }

    internal static string FailureStatus(bool applicationStarted, string origin)
    {
        return applicationStarted
            ? "Dify 已安装并启动；最后检查未完成。可直接打开 " + origin + "/install"
            : "操作失败；未删除现有数据。";
    }

    internal static string Quote(string value)
    {
        if (value.IndexOf('\0') >= 0 || value.IndexOf('\r') >= 0 || value.IndexOf('\n') >= 0)
            throw new InvalidOperationException("Invalid command argument.");
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char ch in value)
        {
            if (ch == '\\') { slashes++; continue; }
            if (ch == '"') { result.Append('\\', slashes * 2 + 1); result.Append(ch); }
            else { result.Append('\\', slashes); result.Append(ch); }
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    internal static string WslExecArguments(string distribution, string command)
    {
        // This WSL version treats quotes around the -d option as literal name characters.
        // Registered conventional names are safe unquoted tokens; Linux path arguments still need quotes.
        if (String.IsNullOrEmpty(distribution) || !System.Text.RegularExpressions.Regex.IsMatch(
            distribution, @"\A[A-Za-z0-9][A-Za-z0-9_.-]*\z"))
            throw new InvalidOperationException("本安装器需要不含空格的常规 WSL 发行版名；请从列表选择发行版。");
        return "-d " + distribution + " --exec " + command;
    }

    internal static string DecodeOutput(byte[] bytes, Encoding fallback)
    {
        Encoding encoding = fallback;
        if (bytes.Length >= 2 && bytes[0] == 0xfe && bytes[1] == 0xff)
            encoding = Encoding.BigEndianUnicode;
        else if ((bytes.Length >= 2 && bytes[0] == 0xff && bytes[1] == 0xfe)
            || bytes.Contains((byte)0))
            encoding = Encoding.Unicode;
        return encoding.GetString(bytes).Trim('\uFEFF');
    }

    internal static string[] Distributions()
    {
        return RunCapture(Wsl, "--list --quiet", Encoding.Unicode, 45000)
            .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(line => line.Replace("\0", "").Trim().Trim('\uFEFF'))
            .Where(name => name.Length > 0 && !name.StartsWith("docker-desktop", StringComparison.OrdinalIgnoreCase))
            .ToArray();
    }

    internal static string ResolveRuntimeScript(string distribution, string windowsPath)
    {
        return RunCapture(Wsl, WslExecArguments(distribution,
            "wslpath -a -u " + Quote(windowsPath)), Encoding.UTF8, 45000).Trim();
    }

    internal static void Extract(Stream input, string target)
    {
        string root = Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        Directory.CreateDirectory(root);
        using (var archive = new ZipArchive(input, ZipArchiveMode.Read))
        {
            foreach (var entry in archive.Entries)
            {
                string destination = Path.GetFullPath(Path.Combine(root, entry.FullName));
                if (!destination.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Unsafe installer payload path.");
                if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(destination); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                using (var source = entry.Open())
                using (var output = new FileStream(destination, FileMode.Create, FileAccess.Write))
                    source.CopyTo(output);
            }
        }
    }

    private static Stream EmbeddedPayload()
    {
        var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("dify.payload.zip");
        if (stream == null) throw new InvalidOperationException("Installer payload is missing.");
        return stream;
    }

    internal static void InstallFiles()
    {
        Directory.CreateDirectory(Home);
        using (var stream = EmbeddedPayload()) Extract(stream, Payload);
        string current = Assembly.GetExecutingAssembly().Location;
        if (!String.Equals(Path.GetFullPath(current), InstalledExe, StringComparison.OrdinalIgnoreCase))
            File.Copy(current, InstalledExe, true);
    }

    internal static string RunCapture(string file, string arguments, Encoding encoding, int timeout)
    {
        var start = new ProcessStartInfo(file, arguments)
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = encoding, StandardErrorEncoding = encoding
        };
        using (var process = Process.Start(start))
        using (var output = new MemoryStream())
        using (var errors = new MemoryStream())
        {
            var copyOutput = process.StandardOutput.BaseStream.CopyToAsync(output);
            var copyErrors = process.StandardError.BaseStream.CopyToAsync(errors);
            if (!process.WaitForExit(timeout))
            {
                try { process.Kill(); } catch { }
                throw new InvalidOperationException("WSL 检查超时，请先启动 WSL 与 Docker。");
            }
            Task.WaitAll(copyOutput, copyErrors);
            string stdout = DecodeOutput(output.ToArray(), encoding);
            string stderr = DecodeOutput(errors.ToArray(), encoding);
            if (process.ExitCode != 0)
                throw new InvalidOperationException("WSL 调用失败（退出码 " + process.ExitCode + "）：\n"
                    + (stdout + "\n" + stderr).Trim());
            return stdout;
        }
    }

    internal static void Open(string target) { Process.Start(new ProcessStartInfo(target) { UseShellExecute = true }); }

    private static void SelfTest(string report)
    {
        string root = Path.Combine(Path.GetTempPath(), "dify-exe-selftest-" + Guid.NewGuid().ToString("N"));
        try
        {
            using (var stream = EmbeddedPayload()) Extract(stream, root);
            foreach (string relative in new[] {
                "docker/docker-compose.yaml", "docker/.env.example", "windows/runtime.sh",
                "windows/local.override.yaml", "windows/shortcuts.ps1", "LICENSE",
                "plugins/amdgpucloud.difypkg", "tools/docker-compose-linux-x86_64",
                "tools/COMPOSE-LICENSE.txt", "安装说明.txt", "THIRD_PARTY_NOTICES.txt" })
                if (!File.Exists(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar))))
                    throw new InvalidDataException("Missing payload file: " + relative);
            foreach (string relative in new[] { "安装说明.txt", "THIRD_PARTY_NOTICES.txt",
                "plugins/INSTALL_windows_zh_Hans.txt", "plugins/README_zh_Hans.md", "plugins/PRIVACY.md" })
                VerifyAttribution(File.ReadAllText(Path.Combine(root,
                    relative.Replace('/', Path.DirectorySeparatorChar)), Encoding.UTF8), relative);
            using (var archive = ZipFile.OpenRead(Path.Combine(root, "plugins", "amdgpucloud.difypkg")))
            {
                if (archive.GetEntry("provider/radeon_cloud.yaml") != null
                    || File.Exists(Path.Combine(root, "plugins", "radeon_cloud.difypkg")))
                    throw new InvalidDataException("Obsolete provider identity is present in payload.");
                foreach (string relative in new[] { "manifest.yaml", "provider/amdgpucloud.yaml",
                    "README.md", "PRIVACY.md", "readme/README_zh_Hans.md", "readme/INSTALL_windows_zh_Hans.txt" })
                {
                    var entry = archive.GetEntry(relative);
                    if (entry == null) throw new InvalidDataException("Missing plugin document: " + relative);
                    using (var reader = new StreamReader(entry.Open(), Encoding.UTF8))
                    {
                        string text = reader.ReadToEnd();
                        VerifyAttribution(text, relative);
                        if (relative == "manifest.yaml" && (!text.Contains("author: letian-kang")
                            || !text.Contains("name: amdgpucloud") || text.Contains("author: joursbleu")
                            || text.Contains("name: radeon_cloud")))
                            throw new InvalidDataException("Plugin identity must be letian-kang/amdgpucloud.");
                        if (relative == "provider/amdgpucloud.yaml"
                            && (!text.Contains("provider: amdgpucloud") || text.Contains("provider: radeon_cloud")))
                            throw new InvalidDataException("Model provider identity must be amdgpucloud.");
                    }
                }
            }
            var assembly = Assembly.GetExecutingAssembly();
            var company = assembly.GetCustomAttributes(typeof(AssemblyCompanyAttribute), false)
                .Cast<AssemblyCompanyAttribute>().Single();
            var contact = assembly.GetCustomAttributes(typeof(AssemblyMetadataAttribute), false)
                .Cast<AssemblyMetadataAttribute>().Single(item => item.Key == "Contact");
            if (company.Company != "Letian Kang" || contact.Value != "Letian.Kang@amd.com")
                throw new InvalidDataException("Windows file attribution is inconsistent.");
            string digest;
            using (var sha = SHA256.Create())
            using (var stream = File.OpenRead(Path.Combine(root, "plugins", "amdgpucloud.difypkg")))
                digest = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
            if (digest != "66f7bd9c8e15136a57228088daa647953d0a373a430d85ee11abff9c5bc5e845")
                throw new InvalidDataException("Plugin payload checksum mismatch.");
            using (var sha = SHA256.Create())
            using (var stream = File.OpenRead(Path.Combine(root, "tools", "docker-compose-linux-x86_64")))
                digest = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
            if (digest != "40343e21ca777173e69cff5dbafeb37c6f81f3b0d57d9e597f036e95eb63e76a")
                throw new InvalidDataException("Compose runtime checksum mismatch.");
            if (LocalOrigin(18080) != "http://127.0.0.1:18080"
                || !FailureStatus(true, LocalOrigin(18080)).Contains("已安装并启动")
                || FailureStatus(true, LocalOrigin(18080)).Contains("操作失败"))
                throw new InvalidDataException("Post-deployment status regression failed.");
            var filesBefore = InstallationFileSnapshot();
            string navigation = null;
            using (var ui = new InstallerForm(null, delegate(string target) { navigation = target; }))
            {
                ui.CreateControl();
                if (!ui.Controls.OfType<Button>().Any(button => button.Text == "安装并启动 Dify"))
                    throw new InvalidDataException("Installer UI action is missing.");
                if (!ui.Controls.OfType<Label>().Any(label => label.Text == IntegrationAttribution))
                    throw new InvalidDataException("Installer author/contact label is missing.");
                if (ui.Controls.OfType<Button>().Any(button => button.Text.Contains("Radeon")
                    || button.Text.Contains("AMDGPUCloud")))
                    throw new InvalidDataException("Provider-specific installer management is not allowed.");
                var management = ui.Controls.OfType<Button>().Single(button => button.Text == "插件管理");
                var selectedPort = ui.Controls.OfType<NumericUpDown>().Single();
                var onClick = typeof(Button).GetMethod("OnClick", BindingFlags.Instance | BindingFlags.NonPublic);
                if (onClick == null) throw new InvalidDataException("Native button click handler is missing.");
                foreach (int testPort in new[] { 18080, 18082 })
                {
                    selectedPort.Value = testPort;
                    onClick.Invoke(management, new object[] { EventArgs.Empty });
                    if (navigation != IntegrationsUrl(testPort))
                        throw new InvalidDataException("Native plugin management navigation failed.");
                }
            }
            var filesAfter = InstallationFileSnapshot();
            if (filesBefore.Count != filesAfter.Count || filesBefore.Any(entry =>
                !filesAfter.ContainsKey(entry.Key) || filesAfter[entry.Key] != entry.Value))
                throw new InvalidDataException("Plugin management must not install or change local files.");
            File.WriteAllText(report, "PASS: native Windows EXE; embedded Dify deployment, Compose runtime, "
                + "letian-kang/amdgpucloud plugin identity and checksum, no obsolete payload, "
                + "WinForms native plugin management (two ports, no file changes), "
                + "author/contact in UI, Windows assembly and embedded documents, and safe payload extraction verified.", Encoding.UTF8);
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static void VerifyAttribution(string text, string source)
    {
        if (!text.Contains("Letian Kang") || !text.Contains("Letian.Kang@amd.com")
            || text.Contains("kangletian@hotmail.com"))
            throw new InvalidDataException("Author/contact mismatch in " + source);
    }

    private static Dictionary<string, DateTime> InstallationFileSnapshot()
    {
        return Directory.Exists(Home)
            ? Directory.GetFiles(Home, "*", SearchOption.AllDirectories)
                .ToDictionary(path => path, path => File.GetLastWriteTimeUtc(path))
            : new Dictionary<string, DateTime>();
    }

    private static void WslSelfTest(string report)
    {
        string root = Path.Combine(Path.GetTempPath(), "dify wsl bridge test " + Guid.NewGuid().ToString("N"));
        try
        {
            string distribution = Distributions().FirstOrDefault();
            if (distribution == null) throw new InvalidOperationException("No usable WSL distribution found.");
            RunCapture(Wsl, WslExecArguments(distribution, "/bin/true"), Encoding.UTF8, 45000);
            using (var stream = EmbeddedPayload()) Extract(stream, root);
            string script = ResolveRuntimeScript(distribution, Path.Combine(root, "windows", "runtime.sh"));
            if (!script.EndsWith("/windows/runtime.sh", StringComparison.Ordinal))
                throw new InvalidOperationException("WSL path conversion returned an unexpected path.");
            string preflight = RunCapture(Wsl, WslExecArguments(distribution,
                "/bin/bash " + Quote(script) + " check 18080 false"), Encoding.UTF8, 60000);
            if (!preflight.Contains("WSL Linux and local Docker ready"))
                throw new InvalidOperationException("The real installer runtime preflight did not succeed.");
            bool diagnosticsVerified = false;
            try
            {
                RunCapture(Wsl, WslExecArguments("DifyMissingDistribution" + Guid.NewGuid().ToString("N"),
                    "/bin/true"), Encoding.UTF8, 45000);
            }
            catch (InvalidOperationException error)
            {
                diagnosticsVerified = error.Message.Contains("WSL_E_DISTRO_NOT_FOUND")
                    && error.Message.Contains("退出码");
            }
            if (!diagnosticsVerified) throw new InvalidOperationException("WSL stdout diagnostic decoding failed.");
            File.WriteAllText(report, "PASS: exact Windows .NET -> WSL distro argument, spaced Windows path, "
                + "embedded runtime check and UTF-16 failure diagnostics verified. Distro=" + distribution
                + ". No services installed or started.", Encoding.UTF8);
        }
        finally { if (Directory.Exists(root)) Directory.Delete(root, true); }
    }

    private static void HttpSelfTest(string report, int port)
    {
        string origin = LocalOrigin(port);
        var timer = Stopwatch.StartNew();
        InstallerForm.VerifyWindowsEndpoint(origin + "/console/api/setup");
        File.WriteAllText(report, "PASS: exact Windows .NET HttpWebRequest to IPv4 Dify setup API; "
            + "URL=" + origin + "/console/api/setup; HTTP=200; elapsedMs=" + timer.ElapsedMilliseconds
            + ". No services installed, restarted or reconfigured.", Encoding.UTF8);
    }
}

internal sealed class InstallerForm : Form
{
    private readonly ComboBox distro = new ComboBox();
    private readonly NumericUpDown port = new NumericUpDown();
    private readonly CheckBox unsigned = new CheckBox();
    private readonly CheckBox license = new CheckBox();
    private readonly TextBox log = new TextBox();
    private readonly Label state = new Label();
    private readonly List<Button> controls = new List<Button>();
    private readonly string initialAction;
    private readonly Action<string> navigate;
    private bool busy;

    internal InstallerForm(string action, Action<string> navigation = null)
    {
        initialAction = action;
        navigate = navigation ?? new Action<string>(Program.Open);
        Text = "Dify 1.17.1 — Windows 安装与启动 · 版本 1.0.8";
        ClientSize = new Size(920, 680);
        MinimumSize = new Size(940, 720);
        Font = new Font("Microsoft YaHei UI", 10);
        BackColor = Color.FromArgb(245, 247, 251);
        StartPosition = FormStartPosition.CenterScreen;
        var title = new Label { Text = "Dify · 本地安装", Font = new Font(Font.FontFamily, 23, FontStyle.Bold),
            Location = new Point(28, 20), Size = new Size(600, 44), ForeColor = Color.FromArgb(32, 43, 64) };
        Controls.Add(title);
        Controls.Add(new Label { Text = "完整平台：Chat / Workflow / RAG / Agent · 使用 Dify 原生插件管理",
            Location = new Point(30, 74), Size = new Size(850, 28), ForeColor = Color.DimGray });
        Controls.Add(new Label { Text = Program.IntegrationAttribution,
            Location = new Point(30, 98), Size = new Size(850, 19), ForeColor = Color.DimGray });
        Controls.Add(new Label { Text = "WSL2 发行版", Location = new Point(30, 119), AutoSize = true });
        distro.Location = new Point(150, 113); distro.Size = new Size(260, 30);
        distro.DropDownStyle = ComboBoxStyle.DropDownList; Controls.Add(distro);
        Controls.Add(new Label { Text = "本机端口", Location = new Point(445, 119), AutoSize = true });
        port.Location = new Point(535, 113); port.Size = new Size(115, 30);
        port.Minimum = 1024; port.Maximum = 65535; port.Value = 18080; Controls.Add(port);
        unsigned.Text = "允许未签名开发插件（仅此新建本地实例，默认关闭）";
        unsigned.Location = new Point(30, 155); unsigned.Size = new Size(820, 28); Controls.Add(unsigned);
        license.Text = "我已阅读 Dify 许可证；用于自己的单工作区，不移除 Dify 标识和版权";
        license.Location = new Point(30, 188); license.Size = new Size(840, 28); Controls.Add(license);
        AddButton("安装并启动 Dify", 30, 232, 175, async delegate { await Execute("install"); }, true);
        AddButton("启动 Dify", 219, 232, 130, async delegate { await Execute("start"); }, false);
        AddButton("停止 Dify", 363, 232, 130, async delegate { await Execute("stop"); }, false);
        AddButton("打开 Dify", 507, 232, 130, delegate { Program.Open(Origin()); }, false);
        AddButton("检查环境", 651, 232, 130, async delegate { await Execute("check"); }, false);
        AddButton("安装说明", 30, 283, 130, delegate { ShowFile("安装说明.txt"); }, false);
        AddButton("Dify 许可证", 174, 283, 140, delegate { ShowFile("LICENSE"); }, false);
        AddButton("插件管理", 328, 283, 150, delegate { OpenIntegrations(); }, false);
        AddButton("Docker / WSL 指引", 492, 283, 200,
            delegate { Program.Open("https://docs.dify.ai/en/self-host/quick-start/docker-compose"); }, false);
        state.Text = "首次安装需联网下载镜像；不删除或接管现有数据。";
        state.Location = new Point(30, 333); state.Size = new Size(850, 30); Controls.Add(state);
        log.Location = new Point(30, 369); log.Size = new Size(855, 275);
        log.Multiline = true; log.ScrollBars = ScrollBars.Vertical; log.ReadOnly = true;
        log.Font = new Font("Consolas", 10); log.BackColor = Color.White;
        log.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(log);
        Shown += async delegate { await LoadDistributions(); };
        FormClosing += delegate(object sender, FormClosingEventArgs args) {
            if (busy) { args.Cancel = true; MessageBox.Show("安装／启动正在进行，请等待本次操作结束。", "Dify"); }
        };
    }

    private void AddButton(string text, int x, int y, int width, EventHandler click, bool primary)
    {
        var button = new Button { Text = text, Location = new Point(x, y), Size = new Size(width, 39),
            FlatStyle = FlatStyle.Flat, BackColor = primary ? Color.FromArgb(49, 94, 232) : Color.White,
            ForeColor = primary ? Color.White : Color.FromArgb(32, 43, 64) };
        button.FlatAppearance.BorderColor = Color.FromArgb(219, 225, 235);
        button.Click += click; Controls.Add(button); controls.Add(button);
    }

    private string Origin() { return Program.LocalOrigin(Decimal.ToInt32(port.Value)); }
    private void ShowFile(string file) { Program.InstallFiles(); Program.Open(Path.Combine(Program.Payload, file)); }
    private void OpenIntegrations()
    {
        // All providers use the same Dify lifecycle; opening management has no installation side effects.
        navigate(Program.IntegrationsUrl(Decimal.ToInt32(port.Value)));
    }
    private void Append(string line)
    {
        if (IsDisposed || line == null) return;
        if (InvokeRequired) { BeginInvoke(new Action<string>(Append), line); return; }
        log.AppendText(line + Environment.NewLine);
    }
    private void SetBusy(bool value)
    {
        busy = value;
        foreach (var button in controls) button.Enabled = !value;
        distro.Enabled = !value; port.Enabled = !value; unsigned.Enabled = !value; license.Enabled = !value;
    }

    private async Task LoadDistributions()
    {
        try
        {
            if (!File.Exists(Program.Wsl)) throw new InvalidOperationException("请先安装并启用 Windows WSL2。");
            string[] names = await Task.Run(delegate { return Program.Distributions(); });
            foreach (string name in names) distro.Items.Add(name);
            if (distro.Items.Count > 0) distro.SelectedIndex = 0;
            if (File.Exists(Program.SettingsPath))
            {
                var saved = XDocument.Load(Program.SettingsPath).Root;
                string name = (string)saved.Element("distro");
                if (distro.Items.Contains(name)) distro.SelectedItem = name;
                port.Value = Int32.Parse((string)saved.Element("port"));
                unsigned.Checked = Boolean.Parse((string)saved.Element("unsigned"));
                license.Checked = true;
            }
            Append("已检测 WSL2 发行版；请先保证该发行版内 docker 命令可用。数据保存到 Linux 文件系统。");
            Append("本安装器不需要本地显卡，也不内置 API Key。首次下载 Dify 镜像可能较慢。");
            if (initialAction == "--open") Program.Open(Origin());
            else if (initialAction == "--start" || initialAction == "--stop")
                await Execute(initialAction.Substring(2));
        }
        catch (Exception error) { Append(error.Message); state.Text = "需要先准备 WSL2 / Docker。"; }
    }

    private async Task Execute(string action)
    {
        if (distro.SelectedItem == null) { MessageBox.Show("请选择可用的 WSL2 Linux 发行版。", "Dify"); return; }
        if (action == "install" && !license.Checked) { MessageBox.Show("请先阅读并确认 Dify 许可证。", "Dify"); return; }
        if (action == "install" && unsigned.Checked && MessageBox.Show(
            "这会仅对新建本地 Dify 实例关闭强制插件签名验证，以安装开发预览插件。\n"
            + "这是实例级设置，不是单插件白名单；不应用于不可信插件或生产服务。是否继续？",
            "未签名开发插件", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
        string selected = distro.SelectedItem.ToString();
        string selectedPort = port.Value.ToString();
        string selectedOrigin = Origin();
        string allow = unsigned.Checked ? "true" : "false";
        bool applicationStarted = false;
        SetBusy(true); state.Text = "正在" + action + "… 日志中不会打印生成的服务密钥。";
        try
        {
            Append("步骤 1/4：核对 WSL2 发行版。");
            string distributionList = await Task.Run(delegate {
                return Program.RunCapture(Program.Wsl, "--list --verbose", Encoding.Unicode, 45000);
            });
            string pattern = @"^\s*\*?\s*" + System.Text.RegularExpressions.Regex.Escape(selected)
                + @"\s+\S+\s+2\s*$";
            if (!distributionList.Replace("\0", "").Split('\n').Any(line =>
                System.Text.RegularExpressions.Regex.IsMatch(line.TrimEnd('\r'), pattern)))
                throw new InvalidOperationException("所选发行版不是 WSL2；请先转换为 WSL2 再安装。");
            Append("步骤 2/4：解包本地部署文件（不修改已有 Dify 数据）。");
            Program.InstallFiles();
            string script = Path.Combine(Program.Payload, "windows", "runtime.sh");
            Append("步骤 3/4：转换 Windows 安装路径到 WSL。");
            string linuxScript = await Task.Run(delegate {
                return Program.ResolveRuntimeScript(selected, script);
            });
            Append("步骤 4/4：运行 Dify 部署脚本。");
            int exit = await Task.Run(delegate {
                return RunLogged(Program.Wsl, Program.WslExecArguments(selected, "bash "
                    + Program.Quote(linuxScript) + " " + action + " " + selectedPort + " " + allow));
            });
            if (exit != 0) throw new InvalidOperationException("操作未完成（退出码 " + exit + "）。请按上方错误检查 Docker、网络或端口。");
            if (action == "install" || action == "start")
            {
                applicationStarted = true;
                state.Text = "Dify 已安装并启动，正在检查 Windows 网页访问…";
                new XDocument(new XElement("settings", new XElement("distro", selected),
                    new XElement("port", selectedPort), new XElement("unsigned", allow)))
                    .Save(Program.SettingsPath);
                string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),
                    "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
                int shortcutExit = await Task.Run(delegate {
                    return RunLogged(powershell, "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "
                        + Program.Quote(Path.Combine(Program.Payload, "windows", "shortcuts.ps1"))
                        + " -ExecutablePath " + Program.Quote(Program.InstalledExe));
                });
                if (shortcutExit != 0) Append("Dify 已运行，但快捷方式创建失败；仍可使用当前 EXE 管理。");
                Append("Windows 网页检测：" + selectedOrigin + "/console/api/setup");
                await Task.Run(delegate { VerifyWindowsEndpoint(selectedOrigin + "/console/api/setup"); });
                Program.Open(selectedOrigin + "/install");
            }
            state.Text = action == "stop" ? "Dify 已停止，数据已保留。"
                : "操作完成；Dify 入口：" + selectedOrigin;
        }
        catch (Exception error)
        {
            Append((applicationStarted ? "WARNING: " : "ERROR: ") + error.Message);
            state.Text = Program.FailureStatus(applicationStarted, selectedOrigin);
            if (applicationStarted)
                Append("服务已成功启动，不要重复安装；请直接打开 " + selectedOrigin + "/install");
        }
        finally { SetBusy(false); }
    }

    private int RunLogged(string file, string arguments)
    {
        var start = new ProcessStartInfo(file, arguments) { UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        using (var process = new Process { StartInfo = start })
        {
            process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs data) { Append(data.Data); };
            process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs data) { Append(data.Data); };
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
            process.WaitForExit(); return process.ExitCode;
        }
    }

    internal static void VerifyWindowsEndpoint(string url)
    {
        var uri = new Uri(url);
        if (uri.Scheme != "http" || uri.Host != "127.0.0.1")
            throw new InvalidOperationException("Windows Dify 检测必须使用 IPv4 本机地址。");
        var request = (System.Net.HttpWebRequest)System.Net.WebRequest.Create(url);
        // Localhost must not be routed through an enterprise HTTP proxy.
        request.Proxy = null;
        request.Timeout = 15000;
        request.ReadWriteTimeout = 15000;
        request.AllowAutoRedirect = false;
        using (var response = (System.Net.HttpWebResponse)request.GetResponse())
            if (response.StatusCode != System.Net.HttpStatusCode.OK)
                throw new InvalidOperationException("Dify 已在 WSL 运行，但 Windows 本机访问失败。");
    }
}