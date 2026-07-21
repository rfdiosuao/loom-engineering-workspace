param(
    [Parameter(Mandatory = $true)]
    [string]$PackageUrl,
    [string[]]$PackageFallbackUrls = @(),
    [Parameter(Mandatory = $true)]
    [string]$PackageSha256,
    [Parameter(Mandatory = $true)]
    [string]$PackageRootName,
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ArtifactsDir = Join-Path $Root "artifacts\installer"
$ReleaseDir = Join-Path $Root "release"
$IconPath = Join-Path $Root "openclaw_new_launcher\src-tauri\icons\icon.ico"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $ReleaseDir "LOOM-Online-Setup-v$Version.exe"
}
if ($PackageRootName -notmatch [regex]::Escape($Version)) {
    throw "Version must match PackageRootName. Version=$Version PackageRootName=$PackageRootName"
}

New-Item -ItemType Directory -Path $ArtifactsDir -Force | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

$cscCandidates = @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
)
$csc = $cscCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $csc) {
    throw "Cannot find .NET Framework csc.exe. Install .NET Framework Developer Pack or use the Tauri NSIS package."
}
if (-not (Test-Path -LiteralPath $IconPath)) {
    throw "Installer icon is missing: $IconPath"
}

$sourcePath = Join-Path $ArtifactsDir "LOOMOnlineInstaller.cs"
$source = @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace LoomOnlineInstaller
{
    static class Program
    {
        public static readonly string[] PackageUrls = new string[] { __PACKAGE_URLS__ };
        public const string PackageSha256 = "__PACKAGE_SHA256__";
        public const string PackageRootName = "__PACKAGE_ROOT_NAME__";
        public const string Version = "__VERSION__";

        [STAThread]
        static int Main(string[] args)
        {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            InstallerOptions options = InstallerOptions.Parse(args);
            if (options.Silent)
            {
                try
                {
                    InstallerCore.Install(
                        options.InstallRoot,
                        null,
                        options.CreateShortcuts,
                        options.LaunchAfterInstall
                    );
                    return 0;
                }
                catch (Exception error)
                {
                    try
                    {
                        File.WriteAllText(
                            Path.Combine(Path.GetTempPath(), "LOOM-online-installer-last-error.txt"),
                            error.ToString()
                        );
                    }
                    catch
                    {
                    }
                    Console.Error.WriteLine(InstallerCore.FriendlyError(error));
                    return 1;
                }
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm(options));
            return 0;
        }
    }

    public sealed class InstallerOptions
    {
        public bool Silent;
        public bool CreateShortcuts = true;
        public bool LaunchAfterInstall = true;
        public string InstallRoot = DefaultInstallRoot();

        public static InstallerOptions Parse(string[] args)
        {
            InstallerOptions options = new InstallerOptions();
            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i] ?? "";
                if (EqualsArg(arg, "/silent") || EqualsArg(arg, "--silent"))
                {
                    options.Silent = true;
                }
                else if (EqualsArg(arg, "/no-launch") || EqualsArg(arg, "--no-launch"))
                {
                    options.LaunchAfterInstall = false;
                }
                else if (EqualsArg(arg, "/no-shortcuts") || EqualsArg(arg, "--no-shortcuts"))
                {
                    options.CreateShortcuts = false;
                }
                else if ((EqualsArg(arg, "/install-dir") || EqualsArg(arg, "--install-dir")) && i + 1 < args.Length)
                {
                    options.InstallRoot = Path.GetFullPath(args[++i]);
                }
            }
            return options;
        }

        private static bool EqualsArg(string actual, string expected)
        {
            return string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase);
        }

        private static string DefaultInstallRoot()
        {
            try
            {
                if (Directory.Exists(@"D:\"))
                {
                    return @"D:\LOOM";
                }
            }
            catch
            {
            }
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "LOOM"
            );
        }
    }

    public sealed class InstallerForm : Form
    {
        private const int SidebarWidth = 160;
        private const int FooterHeight = 52;

        private readonly InstallerOptions options;
        private readonly Panel sidebarPanel = new Panel();
        private readonly Panel contentPanel = new Panel();
        private readonly Panel footerPanel = new Panel();
        private readonly PictureBox logoPictureBox = new PictureBox();
        private readonly Label brandLabel = new Label();
        private readonly Label brandSubtitleLabel = new Label();
        private readonly Label brandFootnoteLabel = new Label();
        private readonly Label titleLabel = new Label();
        private readonly Label bodyLabel = new Label();
        private readonly Label installDirLabel = new Label();
        private readonly TextBox installDirTextBox = new TextBox();
        private readonly Button browseButton = new Button();
        private readonly Label spaceLabel = new Label();
        private readonly Label statusLabel = new Label();
        private readonly ProgressBar progress = new ProgressBar();
        private readonly Button backButton = new Button();
        private readonly Button nextButton = new Button();
        private readonly Button cancelButton = new Button();
        private int stepIndex;
        private bool installing;

        public InstallerForm(InstallerOptions options)
        {
            this.options = options;
            Text = "LOOM " + Program.Version + " \u5b89\u88c5";
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = true;
            ClientSize = new Size(560, 340);
            BackColor = SystemColors.Control;
            Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular);
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);

            sidebarPanel.BackColor = Color.FromArgb(13, 18, 27);
            sidebarPanel.SetBounds(0, 0, SidebarWidth, ClientSize.Height - FooterHeight);

            logoPictureBox.SizeMode = PictureBoxSizeMode.Zoom;
            logoPictureBox.Image = CreateLogoBitmap();
            logoPictureBox.SetBounds(46, 54, 68, 68);

            brandLabel.Text = "LOOM";
            brandLabel.Font = new Font("Segoe UI", 22F, FontStyle.Regular);
            brandLabel.ForeColor = Color.White;
            brandLabel.AutoSize = false;
            brandLabel.TextAlign = ContentAlignment.MiddleCenter;
            brandLabel.SetBounds(12, 140, 136, 36);

            brandSubtitleLabel.Text = "\u9e93\u9e23";
            brandSubtitleLabel.Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular);
            brandSubtitleLabel.ForeColor = Color.FromArgb(155, 166, 180);
            brandSubtitleLabel.AutoSize = false;
            brandSubtitleLabel.TextAlign = ContentAlignment.MiddleCenter;
            brandSubtitleLabel.SetBounds(12, 174, 136, 24);

            brandFootnoteLabel.Text = "AI \u81ea\u52a8\u5316\u542f\u52a8\u5668";
            brandFootnoteLabel.Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular);
            brandFootnoteLabel.ForeColor = Color.FromArgb(122, 132, 146);
            brandFootnoteLabel.AutoSize = false;
            brandFootnoteLabel.TextAlign = ContentAlignment.MiddleCenter;
            brandFootnoteLabel.SetBounds(12, 246, 136, 24);

            sidebarPanel.Controls.Add(logoPictureBox);
            sidebarPanel.Controls.Add(brandLabel);
            sidebarPanel.Controls.Add(brandSubtitleLabel);
            sidebarPanel.Controls.Add(brandFootnoteLabel);

            contentPanel.BackColor = Color.White;
            contentPanel.SetBounds(SidebarWidth, 0, ClientSize.Width - SidebarWidth, ClientSize.Height - FooterHeight);

            titleLabel.Font = new Font("Microsoft YaHei UI", 12F, FontStyle.Bold);
            titleLabel.ForeColor = Color.Black;
            titleLabel.AutoSize = false;
            titleLabel.TextAlign = ContentAlignment.MiddleLeft;
            titleLabel.SetBounds(18, 22, 360, 28);

            bodyLabel.Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular);
            bodyLabel.ForeColor = Color.Black;
            bodyLabel.AutoSize = false;
            bodyLabel.TextAlign = ContentAlignment.TopLeft;
            bodyLabel.SetBounds(18, 74, 360, 112);

            installDirLabel.Text = "\u5b89\u88c5\u76ee\u5f55";
            installDirLabel.Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular);
            installDirLabel.ForeColor = Color.Black;
            installDirLabel.AutoSize = false;
            installDirLabel.TextAlign = ContentAlignment.MiddleLeft;
            installDirLabel.SetBounds(18, 162, 86, 22);

            installDirTextBox.Text = options.InstallRoot;
            installDirTextBox.Font = new Font("Consolas", 9F, FontStyle.Regular);
            installDirTextBox.SetBounds(18, 190, 292, 23);

            browseButton.Text = "\u6d4f\u89c8(&B)...";
            browseButton.SetBounds(320, 188, 72, 26);
            browseButton.Click += delegate { BrowseInstallDir(); };

            spaceLabel.Font = new Font("Microsoft YaHei UI", 8.5F, FontStyle.Regular);
            spaceLabel.ForeColor = Color.Black;
            spaceLabel.AutoSize = false;
            spaceLabel.TextAlign = ContentAlignment.TopLeft;
            spaceLabel.SetBounds(18, 222, 360, 60);

            statusLabel.Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular);
            statusLabel.ForeColor = Color.Black;
            statusLabel.AutoSize = false;
            statusLabel.TextAlign = ContentAlignment.MiddleLeft;
            statusLabel.SetBounds(18, 170, 360, 48);

            progress.Minimum = 0;
            progress.Maximum = 100;
            progress.Value = 0;
            progress.SetBounds(18, 134, 360, 18);

            contentPanel.Controls.Add(titleLabel);
            contentPanel.Controls.Add(bodyLabel);
            contentPanel.Controls.Add(installDirLabel);
            contentPanel.Controls.Add(installDirTextBox);
            contentPanel.Controls.Add(browseButton);
            contentPanel.Controls.Add(spaceLabel);
            contentPanel.Controls.Add(statusLabel);
            contentPanel.Controls.Add(progress);

            footerPanel.BackColor = SystemColors.Control;
            footerPanel.SetBounds(0, ClientSize.Height - FooterHeight, ClientSize.Width, FooterHeight);
            Panel footerLine = new Panel();
            footerLine.BackColor = SystemColors.ControlDark;
            footerLine.SetBounds(0, 0, ClientSize.Width, 1);
            footerPanel.Controls.Add(footerLine);

            backButton.Text = "< \u4e0a\u4e00\u6b65(&P)";
            backButton.SetBounds(312, 16, 74, 25);
            backButton.Click += delegate { GoBack(); };

            nextButton.Text = "\u4e0b\u4e00\u6b65(&N) >";
            nextButton.SetBounds(390, 16, 76, 25);
            nextButton.Click += async delegate { await GoNextAsync(); };

            cancelButton.Text = "\u53d6\u6d88(&C)";
            cancelButton.SetBounds(476, 16, 72, 25);
            cancelButton.Click += delegate { Close(); };

            footerPanel.Controls.Add(backButton);
            footerPanel.Controls.Add(nextButton);
            footerPanel.Controls.Add(cancelButton);

            Controls.Add(sidebarPanel);
            Controls.Add(contentPanel);
            Controls.Add(footerPanel);

            ShowStep(0);
        }

        private static Bitmap CreateLogoBitmap()
        {
            Icon icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            if (icon == null)
            {
                icon = SystemIcons.Application;
            }
            return icon.ToBitmap();
        }

        private void BrowseInstallDir()
        {
            using (FolderBrowserDialog dialog = new FolderBrowserDialog())
            {
                dialog.Description = "\u9009\u62e9 LOOM \u5b89\u88c5\u76ee\u5f55";
                dialog.SelectedPath = installDirTextBox.Text;
                dialog.ShowNewFolderButton = true;
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    installDirTextBox.Text = dialog.SelectedPath;
                    UpdateSpaceLabel();
                }
            }
        }

        private void GoBack()
        {
            if (installing || stepIndex <= 0)
            {
                return;
            }
            ShowStep(stepIndex - 1);
        }

        private async Task GoNextAsync()
        {
            if (installing)
            {
                return;
            }
            if (stepIndex == 0)
            {
                ShowStep(1);
                return;
            }
            if (stepIndex == 1)
            {
                await InstallAsync();
                return;
            }
            if (stepIndex == 3)
            {
                Close();
            }
        }

        private void ShowStep(int nextStep)
        {
            stepIndex = nextStep;
            installDirLabel.Visible = stepIndex == 1;
            installDirTextBox.Visible = stepIndex == 1;
            browseButton.Visible = stepIndex == 1;
            spaceLabel.Visible = stepIndex == 1;
            progress.Visible = stepIndex == 2;
            statusLabel.Visible = stepIndex == 2;
            bodyLabel.Visible = stepIndex != 2;

            backButton.Enabled = !installing && stepIndex > 0 && stepIndex < 3;
            cancelButton.Enabled = !installing && stepIndex < 3;

            if (stepIndex == 0)
            {
                titleLabel.Text = "\u6b22\u8fce\u5b89\u88c5 LOOM";
                bodyLabel.Text = "\u5373\u5c06\u628a LOOM " + Program.Version + " \u5b89\u88c5\u5230\u4f60\u7684\u7535\u8111\u3002\r\n\r\n\u9996\u6b21\u542f\u52a8\u4f1a\u81ea\u52a8\u4e0b\u8f7d\u5fc5\u8981\u8fd0\u884c\u7ec4\u4ef6\uff0c\u8bf7\u4fdd\u6301\u8054\u7f51\u3002\r\n\r\n\u70b9\u51fb\u300c\u4e0b\u4e00\u6b65\u300d\u7ee7\u7eed\u3002";
                nextButton.Text = "\u4e0b\u4e00\u6b65(&N) >";
                nextButton.Enabled = true;
            }
            else if (stepIndex == 1)
            {
                titleLabel.Text = "\u9009\u62e9\u5b89\u88c5\u4f4d\u7f6e";
                bodyLabel.Text = "\u9009\u62e9 LOOM " + Program.Version + " \u7684\u5b89\u88c5\u6587\u4ef6\u5939\u3002\r\n\r\n\u8fd9\u91cc\u53ea\u662f\u5b89\u88c5\u76ee\u5f55\uff1b\u4e0b\u8f7d\u7f13\u5b58\u4f1a\u4f7f\u7528\u7cfb\u7edf\u4e34\u65f6\u76ee\u5f55\uff0c\u5b89\u88c5\u5b8c\u6210\u540e\u81ea\u52a8\u6e05\u7406\u3002";
                nextButton.Text = "\u5b89\u88c5(&I)";
                nextButton.Enabled = true;
                UpdateSpaceLabel();
            }
            else if (stepIndex == 2)
            {
                titleLabel.Text = "\u6b63\u5728\u5b89\u88c5 LOOM";
                statusLabel.Text = "\u6b63\u5728\u51c6\u5907\u5b89\u88c5...";
                nextButton.Text = "\u5b89\u88c5(&I)";
                nextButton.Enabled = false;
            }
            else
            {
                titleLabel.Text = "\u5b89\u88c5\u5b8c\u6210";
                bodyLabel.Text = "LOOM \u9e93\u9e23\u5df2\u5b89\u88c5\u5b8c\u6210\u3002\r\n\r\n\u4f60\u53ef\u4ee5\u4ece\u684c\u9762\u6216\u5f00\u59cb\u83dc\u5355\u542f\u52a8 LOOM\u3002";
                nextButton.Text = "\u5b8c\u6210(&F)";
                nextButton.Enabled = true;
            }
        }

        private void UpdateSpaceLabel()
        {
            try
            {
                string root = Path.GetPathRoot(Path.GetFullPath(installDirTextBox.Text));
                DriveInfo drive = new DriveInfo(root);
                spaceLabel.Text = "\u5b89\u88c5\u6240\u9700\u7a7a\u95f4\uff1a\u7ea6 80 MB\r\n\u4e0b\u8f7d\u7f13\u5b58\uff1a\u7cfb\u7edf\u4e34\u65f6\u76ee\u5f55\uff08\u5b8c\u6210\u540e\u6e05\u7406\uff09\r\n\u5f53\u524d\u78c1\u76d8\u53ef\u7528\u7a7a\u95f4\uff1a" + FormatBytes(drive.AvailableFreeSpace);
            }
            catch
            {
                spaceLabel.Text = "\u5b89\u88c5\u6240\u9700\u7a7a\u95f4\uff1a\u7ea6 80 MB\r\n\u4e0b\u8f7d\u7f13\u5b58\uff1a\u7cfb\u7edf\u4e34\u65f6\u76ee\u5f55\uff08\u5b8c\u6210\u540e\u6e05\u7406\uff09\r\n\u5f53\u524d\u78c1\u76d8\u53ef\u7528\u7a7a\u95f4\uff1a\u672a\u77e5";
            }
        }

        private static string FormatBytes(long bytes)
        {
            double value = bytes;
            string[] units = new[] { "B", "KB", "MB", "GB", "TB" };
            int index = 0;
            while (value >= 1024 && index < units.Length - 1)
            {
                value /= 1024;
                index++;
            }
            return value.ToString("0.0") + " " + units[index];
        }

        private async Task InstallAsync()
        {
            try
            {
                string rawInstallRoot = installDirTextBox.Text.Trim();
                if (string.IsNullOrEmpty(rawInstallRoot))
                {
                    throw new InvalidOperationException("\u8bf7\u5148\u9009\u62e9\u5b89\u88c5\u76ee\u5f55\u3002");
                }
                string installRoot = Path.GetFullPath(rawInstallRoot);
                InstallerCore.ValidateInstallRoot(installRoot);
                options.InstallRoot = installRoot;
                ShowStep(2);
                SetInstalling(true);
                await Task.Run(delegate
                {
                    InstallerCore.Install(
                        installRoot,
                        new UiProgress(SetStatus, SetProgress),
                        options.CreateShortcuts,
                        options.LaunchAfterInstall
                    );
                });
                SetProgress(100);
                SetStatus("\u5b89\u88c5\u5b8c\u6210\uff0cLOOM \u5df2\u51c6\u5907\u5c31\u7eea\u3002");
                SetInstalling(false);
                ShowStep(3);
            }
            catch (Exception error)
            {
                string message = InstallerCore.FriendlyError(error);
                SetStatus("\u5b89\u88c5\u5931\u8d25\uff1a" + message);
                SetInstalling(false);
                ShowStep(1);
                MessageBox.Show(this, message, "LOOM \u5b89\u88c5\u5931\u8d25", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void SetInstalling(bool installing)
        {
            this.installing = installing;
            installDirTextBox.Enabled = !installing;
            browseButton.Enabled = !installing;
            backButton.Enabled = !installing && stepIndex > 0 && stepIndex < 3;
            nextButton.Enabled = !installing && stepIndex != 2;
            cancelButton.Enabled = !installing && stepIndex < 3;
        }

        private void SetStatus(string text)
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action<string>(SetStatus), text);
                return;
            }
            statusLabel.Text = text;
        }

        private void SetProgress(int value)
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action<int>(SetProgress), value);
                return;
            }
            progress.Value = Math.Max(progress.Minimum, Math.Min(progress.Maximum, value));
        }
    }

    sealed class UiProgress
    {
        private readonly Action<string> setStatus;
        private readonly Action<int> setProgress;

        public UiProgress(Action<string> setStatus, Action<int> setProgress)
        {
            this.setStatus = setStatus;
            this.setProgress = setProgress;
        }

        public void Status(string text)
        {
            setStatus(text);
        }

        public void Progress(int value)
        {
            setProgress(value);
        }
    }

    static class InstallerCore
    {
        public static void Install(string installRoot, UiProgress ui, bool createShortcuts, bool launchAfterInstall)
        {
            installRoot = Path.GetFullPath(installRoot);
            ValidateInstallRoot(installRoot);
            string workDir = CreateShortWorkDir(installRoot);
            string zipPath = Path.Combine(workDir, "loom-online.zip");
            string stageDir = Path.Combine(workDir, "stage");
            try
            {
                Directory.CreateDirectory(workDir);
                Directory.CreateDirectory(stageDir);

                Status(ui, "\u6b63\u5728\u4e0b\u8f7d\u5230\u7cfb\u7edf\u4e34\u65f6\u76ee\u5f55...");
                Download(Program.PackageUrls, zipPath, ui);

                Status(ui, "\u6b63\u5728\u6821\u9a8c\u5b89\u88c5\u5305...");
                string hash = Sha256(zipPath);
                if (!hash.Equals(Program.PackageSha256, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidOperationException("\u5b89\u88c5\u5305\u6821\u9a8c\u5931\u8d25\u3002\u8bf7\u91cd\u65b0\u4e0b\u8f7d\u5b89\u88c5\u5668\uff0c\u6216\u7a0d\u540e\u91cd\u8bd5\u3002");
                }
                Progress(ui, 62);

                Status(ui, "\u6b63\u5728\u89e3\u538b\u5b89\u88c5\u6587\u4ef6...");
                ExtractPackage(zipPath, stageDir);
                Progress(ui, 74);

                Status(ui, "\u6b63\u5728\u5b89\u88c5\u5230 " + installRoot);
                InstallFiles(stageDir, installRoot);
                Progress(ui, 88);

                if (createShortcuts)
                {
                    Status(ui, "\u6b63\u5728\u521b\u5efa\u684c\u9762\u548c\u5f00\u59cb\u83dc\u5355\u5feb\u6377\u65b9\u5f0f...");
                    CreateShortcuts(installRoot);
                }
                Progress(ui, 96);

                if (launchAfterInstall)
                {
                    Status(ui, "\u5b89\u88c5\u5b8c\u6210\uff0c\u6b63\u5728\u542f\u52a8 LOOM...");
                    LaunchLoom(installRoot);
                }
            }
            finally
            {
                TryDelete(workDir);
            }
        }

        public static void ValidateInstallRoot(string installRoot)
        {
            if (string.IsNullOrWhiteSpace(installRoot))
            {
                throw new InvalidOperationException("\u8bf7\u5148\u9009\u62e9\u5b89\u88c5\u76ee\u5f55\u3002");
            }
            string fullPath = Path.GetFullPath(installRoot);
            if (fullPath.Length > 140)
            {
                throw new InvalidOperationException("\u5b89\u88c5\u76ee\u5f55\u8def\u5f84\u592a\u957f\u3002\u8bf7\u6539\u7528 D:\\LOOM \u6216 C:\\LOOM \u8fd9\u6837\u7684\u77ed\u8def\u5f84\uff0c\u907f\u514d Windows \u8def\u5f84\u957f\u5ea6\u9650\u5236\u5bfc\u81f4\u5b89\u88c5\u5931\u8d25\u3002");
            }
        }

        private static string CreateShortWorkDir(string installRoot)
        {
            string root = "";
            try
            {
                root = Path.GetPathRoot(Path.GetFullPath(installRoot));
            }
            catch
            {
                root = Path.GetPathRoot(Path.GetTempPath());
            }
            if (string.IsNullOrEmpty(root))
            {
                root = Path.GetPathRoot(Path.GetTempPath());
            }
            string parent = Path.Combine(root, ".loomtmp");
            return Path.Combine(parent, Guid.NewGuid().ToString("N").Substring(0, 8));
        }

        private static void Download(string[] urls, string target, UiProgress ui)
        {
            Exception lastError = null;
            for (int i = 0; i < urls.Length; i++)
            {
                string url = urls[i];
                try
                {
                    if (File.Exists(target))
                    {
                        File.Delete(target);
                    }
                    Status(ui, "\u6b63\u5728\u5c1d\u8bd5\u4e0b\u8f7d\u901a\u9053 " + (i + 1) + "/" + urls.Length + "...");
                    DownloadOne(url, target, ui);
                    return;
                }
                catch (Exception error)
                {
                    lastError = error;
                }
            }
            throw new WebException("\u6240\u6709\u5b89\u88c5\u5305\u4e0b\u8f7d\u901a\u9053\u5747\u4e0d\u53ef\u7528\u3002", lastError);
        }

        private static void DownloadOne(string url, string target, UiProgress ui)
        {
            if (url.StartsWith("parts:", StringComparison.OrdinalIgnoreCase))
            {
                DownloadParts(url.Substring("parts:".Length), target, ui);
                return;
            }

            if (TryCurlDownload(url, target, ui))
            {
                return;
            }

            using (TimeoutWebClient client = new TimeoutWebClient())
            {
                client.DownloadProgressChanged += delegate(object sender, DownloadProgressChangedEventArgs e)
                {
                    Progress(ui, Math.Min(60, Math.Max(1, e.ProgressPercentage * 60 / 100)));
                    Status(ui, "\u6b63\u5728\u4e0b\u8f7d\u5230\u7cfb\u7edf\u4e34\u65f6\u76ee\u5f55... " + e.ProgressPercentage + "%");
                };
                client.DownloadFileTaskAsync(new Uri(url), target).GetAwaiter().GetResult();
            }
        }

        private static void DownloadParts(string partsSpec, string target, UiProgress ui)
        {
            string[] partUrls = partsSpec.Split(new char[] { ';' }, StringSplitOptions.RemoveEmptyEntries);
            if (partUrls.Length == 0)
            {
                throw new WebException("\u5206\u7247\u4e0b\u8f7d\u901a\u9053\u914d\u7f6e\u4e3a\u7a7a\u3002");
            }

            string partDir = Path.Combine(Path.GetDirectoryName(target), "parts-" + Guid.NewGuid().ToString("N").Substring(0, 8));
            Directory.CreateDirectory(partDir);
            try
            {
                string[] partPaths = new string[partUrls.Length];
                for (int i = 0; i < partUrls.Length; i++)
                {
                    string partPath = Path.Combine(partDir, "package.part" + (i + 1).ToString("000"));
                    partPaths[i] = partPath;
                    Status(ui, "\u6b63\u5728\u4e0b\u8f7d\u5b89\u88c5\u5305\u5206\u7247 " + (i + 1) + "/" + partUrls.Length + "...");
                    DownloadOne(partUrls[i], partPath, ui);
                    Progress(ui, Math.Min(60, Math.Max(1, ((i + 1) * 60) / partUrls.Length)));
                }

                Status(ui, "\u6b63\u5728\u5408\u5e76\u5b89\u88c5\u5305\u5206\u7247...");
                using (FileStream output = File.Create(target))
                {
                    for (int i = 0; i < partPaths.Length; i++)
                    {
                        using (FileStream input = File.OpenRead(partPaths[i]))
                        {
                            input.CopyTo(output);
                        }
                    }
                }
            }
            finally
            {
                try
                {
                    Directory.Delete(partDir, true);
                }
                catch
                {
                }
            }
        }

        private static bool TryCurlDownload(string url, string target, UiProgress ui)
        {
            try
            {
                Status(ui, "\u6b63\u5728\u4f7f\u7528\u7cfb\u7edf\u4e0b\u8f7d\u901a\u9053...");
                ProcessStartInfo startInfo = new ProcessStartInfo();
                startInfo.FileName = "curl.exe";
                startInfo.Arguments = "-fL --connect-timeout 20 --speed-limit 32768 --speed-time 60 --max-time 600 -o " + Quote(target) + " " + Quote(url);
                startInfo.CreateNoWindow = true;
                startInfo.UseShellExecute = false;
                startInfo.RedirectStandardError = true;
                using (Process process = Process.Start(startInfo))
                {
                    if (process == null)
                    {
                        return false;
                    }
                    string stderr = process.StandardError.ReadToEnd();
                    process.WaitForExit();
                    if (process.ExitCode == 0)
                    {
                        return true;
                    }
                    throw new WebException("\u4e0b\u8f7d\u901a\u9053\u8fc7\u6162\u6216\u4e0d\u53ef\u7528\u3002" + stderr);
                }
            }
            catch (Win32Exception)
            {
                return false;
            }
        }

        private static string Quote(string value)
        {
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }

        private sealed class TimeoutWebClient : WebClient
        {
            protected override WebRequest GetWebRequest(Uri address)
            {
                WebRequest request = base.GetWebRequest(address);
                request.Timeout = 60000;
                HttpWebRequest http = request as HttpWebRequest;
                if (http != null)
                {
                    http.ReadWriteTimeout = 60000;
                    http.KeepAlive = false;
                }
                return request;
            }
        }

        private static void ExtractPackage(string zipPath, string targetDir)
        {
            using (ZipArchive archive = ZipFile.OpenRead(zipPath))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string relative = NormalizeEntryPath(entry.FullName);
                    if (string.IsNullOrEmpty(relative))
                    {
                        continue;
                    }
                    string destination = Path.Combine(targetDir, relative);
                    string fullTargetDir = Path.GetFullPath(targetDir);
                    string fullDestination = Path.GetFullPath(destination);
                    if (!fullDestination.StartsWith(fullTargetDir, StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidOperationException("\u5b89\u88c5\u5305\u5185\u5bb9\u4e0d\u5b89\u5168\uff1a" + entry.FullName);
                    }
                    if (entry.FullName.EndsWith("/", StringComparison.Ordinal) || entry.FullName.EndsWith("\\", StringComparison.Ordinal))
                    {
                        Directory.CreateDirectory(fullDestination);
                        continue;
                    }
                    string parent = Path.GetDirectoryName(fullDestination);
                    if (!string.IsNullOrEmpty(parent))
                    {
                        Directory.CreateDirectory(parent);
                    }
                    entry.ExtractToFile(fullDestination, true);
                }
            }
            if (!File.Exists(Path.Combine(targetDir, "LOOM.exe")))
            {
                throw new InvalidOperationException("\u5b89\u88c5\u5305\u5185\u5bb9\u4e0d\u5b8c\u6574\uff1a\u6ca1\u6709\u627e\u5230 LOOM.exe\u3002");
            }
        }

        private static string NormalizeEntryPath(string fullName)
        {
            string normalized = (fullName ?? "").Replace('\\', '/').Trim('/');
            if (normalized.Length == 0)
            {
                return "";
            }
            string prefix = Program.PackageRootName.Trim('/') + "/";
            if (normalized.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                normalized = normalized.Substring(prefix.Length);
            }
            normalized = normalized.Replace('/', Path.DirectorySeparatorChar);
            if (normalized.IndexOf("..", StringComparison.Ordinal) >= 0 || Path.IsPathRooted(normalized))
            {
                throw new InvalidOperationException("\u5b89\u88c5\u5305\u5185\u5bb9\u4e0d\u5b89\u5168\uff1a" + fullName);
            }
            return normalized;
        }

        private static void InstallFiles(string source, string target)
        {
            target = Path.GetFullPath(target);
            string parent = Path.GetDirectoryName(target);
            if (string.IsNullOrEmpty(parent))
            {
                throw new InvalidOperationException("\u5b89\u88c5\u76ee\u5f55\u65e0\u6548\uff1a" + target);
            }
            Directory.CreateDirectory(parent);

            string backup = "";
            if (Directory.Exists(target))
            {
                if (DirectoryContainsUserFiles(target) && !IsRecognizedLoomInstallDirectory(target))
                {
                    throw new InvalidOperationException("\u76ee\u6807\u76ee\u5f55\u4e0d\u662f LOOM \u5b89\u88c5\u76ee\u5f55\u3002\u8bf7\u9009\u62e9\u7a7a\u76ee\u5f55\uff0c\u6216\u9009\u62e9\u5df2\u6709 LOOM \u5b89\u88c5\u76ee\u5f55\u8fdb\u884c\u8986\u76d6\u5b89\u88c5\u3002");
                }
                backup = NextBackupPath(target);
                MoveDirectorySafe(target, backup);
            }
            try
            {
                CopyDirectory(source, target);
                if (!string.IsNullOrEmpty(backup))
                {
                    RestoreUserData(backup, target);
                }
            }
            catch
            {
                TryDelete(target);
                if (!string.IsNullOrEmpty(backup) && Directory.Exists(backup))
                {
                    MoveDirectorySafe(backup, target);
                }
                throw;
            }
            finally
            {
                // Keep the previous install backup for manual rollback instead of deleting user data permanently.
            }
        }

        private static bool DirectoryContainsUserFiles(string target)
        {
            try
            {
                return Directory.Exists(target) && Directory.EnumerateFileSystemEntries(target).GetEnumerator().MoveNext();
            }
            catch
            {
                return true;
            }
        }

        private static bool IsRecognizedLoomInstallDirectory(string target)
        {
            return File.Exists(Path.Combine(target, "LOOM.exe"))
                || Directory.Exists(Path.Combine(target, "LOOMFiles"))
                || File.Exists(Path.Combine(target, "README-ONLINE.txt"));
        }

        private static string NextBackupPath(string target)
        {
            string parent = Path.GetDirectoryName(target);
            string name = Path.GetFileName(target.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
            string stamp = DateTime.Now.ToString("yyyyMMddHHmmss");
            for (int i = 0; i < 50; i++)
            {
                string suffix = i == 0 ? "" : "-" + i.ToString();
                string candidate = Path.Combine(parent, name + ".backup-" + stamp + suffix);
                if (!Directory.Exists(candidate) && !File.Exists(candidate))
                {
                    return candidate;
                }
            }
            throw new InvalidOperationException("\u65e0\u6cd5\u521b\u5efa\u5b89\u88c5\u5907\u4efd\u76ee\u5f55\uff1a" + target);
        }

        private static void MoveDirectorySafe(string source, string target)
        {
            try
            {
                Directory.Move(source, target);
                return;
            }
            catch (IOException error)
            {
                if (!IsCrossVolumeMoveError(error))
                {
                    throw;
                }
            }
            CopyDirectory(source, target);
            TryDelete(source);
        }

        private static bool IsCrossVolumeMoveError(IOException error)
        {
            int lowWord = error.HResult & 0xFFFF;
            if (lowWord == 17)
            {
                return true;
            }
            string message = error.Message ?? "";
            return message.IndexOf("same root", StringComparison.OrdinalIgnoreCase) >= 0
                || message.IndexOf("\u76f8\u540c\u7684\u6839", StringComparison.OrdinalIgnoreCase) >= 0
                || message.IndexOf("\u5377\u4e4b\u95f4", StringComparison.OrdinalIgnoreCase) >= 0
                || message.IndexOf("between volumes", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static void RestoreUserData(string backup, string target)
        {
            string oldData = Path.Combine(backup, "LOOMFiles", "data");
            string newData = Path.Combine(target, "LOOMFiles", "data");
            if (Directory.Exists(oldData))
            {
                CopyDirectory(oldData, newData);
            }
        }

        private static void CopyDirectory(string source, string target)
        {
            Directory.CreateDirectory(target);
            foreach (string file in Directory.GetFiles(source))
            {
                File.Copy(file, Path.Combine(target, Path.GetFileName(file)), true);
            }
            foreach (string dir in Directory.GetDirectories(source))
            {
                CopyDirectory(dir, Path.Combine(target, Path.GetFileName(dir)));
            }
        }

        private static void CreateShortcuts(string root)
        {
            string exe = Path.Combine(root, "LOOM.exe");
            string desktop = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "LOOM \u9e93\u9e23.lnk");
            string startDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.StartMenu), "Programs", "LOOM");
            Directory.CreateDirectory(startDir);
            CreateShortcut(desktop, exe, root);
            CreateShortcut(Path.Combine(startDir, "LOOM \u9e93\u9e23.lnk"), exe, root);
        }

        private static void CreateShortcut(string shortcutPath, string targetPath, string workingDirectory)
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            dynamic shell = Activator.CreateInstance(shellType);
            dynamic shortcut = shell.CreateShortcut(shortcutPath);
            shortcut.TargetPath = targetPath;
            shortcut.WorkingDirectory = workingDirectory;
            shortcut.IconLocation = targetPath;
            shortcut.Description = "LOOM \u9e93\u9e23";
            shortcut.Save();
        }

        private static void LaunchLoom(string root)
        {
            string exe = Path.Combine(root, "LOOM.exe");
            if (!File.Exists(exe))
            {
                throw new FileNotFoundException("\u6ca1\u6709\u627e\u5230 LOOM.exe", exe);
            }
            Process.Start(new ProcessStartInfo
            {
                FileName = exe,
                WorkingDirectory = root,
                UseShellExecute = true
            });
        }

        private static string Sha256(string path)
        {
            using (FileStream stream = File.OpenRead(path))
            using (SHA256 sha = SHA256.Create())
            {
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "");
            }
        }

        public static string FriendlyError(Exception error)
        {
            if (error is WebException)
            {
                return "\u4e0b\u8f7d\u5b89\u88c5\u5305\u5931\u8d25\u3002\u8bf7\u68c0\u67e5\u7f51\u7edc\uff0c\u6216\u7a0d\u540e\u91cd\u8bd5\u56fd\u5185\u6e90 / GitHub \u5907\u7528\u901a\u9053\u3002";
            }
            if (error is PathTooLongException)
            {
                return "\u5b89\u88c5\u76ee\u5f55\u8def\u5f84\u592a\u957f\u3002\u8bf7\u6539\u7528 D:\\LOOM \u6216 C:\\LOOM \u8fd9\u6837\u7684\u77ed\u8def\u5f84\u540e\u91cd\u8bd5\u3002";
            }
            return error.Message;
        }

        private static void Status(UiProgress ui, string text)
        {
            if (ui != null)
            {
                ui.Status(text);
            }
        }

        private static void Progress(UiProgress ui, int value)
        {
            if (ui != null)
            {
                ui.Progress(value);
            }
        }

        private static void TryDelete(string path)
        {
            try
            {
                if (Directory.Exists(path))
                {
                    Directory.Delete(path, true);
                }
            }
            catch
            {
            }
        }
    }
}
'@

$packageUrls = @($PackageUrl) + @($PackageFallbackUrls) |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    Select-Object -Unique
if ($packageUrls.Count -lt 1) {
    throw "At least one package URL is required."
}
$packageUrlLiteral = ($packageUrls | ForEach-Object {
    '"' + (($_ -replace '\\', '\\') -replace '"', '\"') + '"'
}) -join ", "

$source = $source.Replace("__PACKAGE_URLS__", $packageUrlLiteral)
$source = $source.Replace("__PACKAGE_SHA256__", $PackageSha256.ToUpperInvariant())
$source = $source.Replace("__PACKAGE_ROOT_NAME__", $PackageRootName)
$source = $source.Replace("__VERSION__", $Version)
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($sourcePath, $source, $utf8NoBom)

Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
& $csc `
    /nologo `
    /target:winexe `
    /codepage:65001 `
    /platform:anycpu `
    /optimize+ `
    /win32icon:"$IconPath" `
    /out:"$OutputPath" `
    /reference:System.dll `
    /reference:System.Core.dll `
    /reference:System.Drawing.dll `
    /reference:System.Windows.Forms.dll `
    /reference:System.IO.Compression.dll `
    /reference:System.IO.Compression.FileSystem.dll `
    $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "csc failed with exit code $LASTEXITCODE"
}

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath
"$($hash.Hash)  $(Split-Path -Leaf $OutputPath)" |
    Set-Content -LiteralPath "$OutputPath.sha256.txt" -Encoding ASCII

Write-Host "Installer: $OutputPath"
Write-Host "SHA256: $($hash.Hash)"
