using System.Drawing;
using System.Reflection;

internal static class AppIcon
{
    internal static Icon Load()
    {
        using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("OutfitColours.ico"))
        using (var icon = new Icon(stream, 32, 32))
            return (Icon)icon.Clone();
    }
}
