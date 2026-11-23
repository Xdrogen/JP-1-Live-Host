using System;
using System.Drawing;
using System.Windows.Forms;
using System.Runtime.InteropServices;
using System.Diagnostics;
using System.IO;

class Boot : Form {
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr FindWindow(string cls, string name);

    Timer t; double v = 0; Image img; DateTime t0; int W = 960, H = 540;

    Boot() {
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false;
        TopMost = true;
        DoubleBuffered = true;
        var sc = Screen.PrimaryScreen.Bounds;
        SetBounds((sc.Width - W) / 2, (sc.Height - H) / 2, W, H);
        string d = AppDomain.CurrentDomain.BaseDirectory;
        string sp = Path.Combine(d, "splash.png");
        if (File.Exists(sp)) { try { img = Image.FromFile(sp); } catch {} }
        try { Icon = new Icon(Path.Combine(d, "jamjum.ico")); } catch {}
        string core = Path.Combine(d, "jamjum_core.exe");
        if (File.Exists(core)) {
            try { Process.Start(new ProcessStartInfo(core) { WorkingDirectory = d }); } catch {}
        }
        t0 = DateTime.Now;
        t = new Timer(); t.Interval = 28; t.Tick += Tick; t.Start();
    }
    void Tick(object s, EventArgs e) {
        if (FindWindow(null, "JP-1 Live Host") != IntPtr.Zero) { t.Stop(); Close(); return; }
        if ((DateTime.Now - t0).TotalSeconds > 40) { t.Stop(); Close(); return; }
        v = Math.Min(94.0, v + 1.4);
        Invalidate();
    }
    protected override void OnPaint(PaintEventArgs e) {
        var g = e.Graphics;
        if (img != null) g.DrawImage(img, 0, 0, Width, Height);
        else g.Clear(Color.FromArgb(16, 20, 28));
        int y = Height - 8;
        using (var a = new SolidBrush(Color.FromArgb(48, 54, 62))) g.FillRectangle(a, 0, y, Width, 6);
        using (var b = new SolidBrush(Color.White)) g.FillRectangle(b, 0, y, (int)(Width * v / 100.0), 6);
    }
    [STAThread] static void Main() {
        Application.EnableVisualStyles();
        Application.Run(new Boot());
    }
}