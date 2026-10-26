using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

static class LocalSetup {
    public static string SteamLaunchUri(string game){
        var folder=new DirectoryInfo(game);if(folder.Parent==null||folder.Parent.Parent==null)return null;
        string apps=folder.Parent.Parent.FullName;
        foreach(string path in Directory.GetFiles(apps,"appmanifest_*.acf")){
            string text=File.ReadAllText(path);var directory=Regex.Match(text,"\"installdir\"\\s+\"([^\"]+)\"");var id=Regex.Match(text,"\"appid\"\\s+\"([0-9]+)\"");
            if(directory.Success&&id.Success&&String.Equals(directory.Groups[1].Value,folder.Name,StringComparison.OrdinalIgnoreCase))return "steam://rungameid/"+id.Groups[1].Value;
        }
        return null;
    }
    public static readonly string Folder=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"OutfitColoursPreparer");
    public static readonly string SettingsPath=Path.Combine(Folder,"Settings.json");
    public static string FindGame(){
        var steam=new List<string>();
        string saved=null;
        try{saved=Registry.GetValue(@"HKEY_CURRENT_USER\Software\Valve\Steam","SteamPath",null) as string;}catch(System.Security.SecurityException){}catch(UnauthorizedAccessException){}
        if(!String.IsNullOrEmpty(saved))steam.Add(saved);
        steam.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),"Steam"));
        var libraries=new List<string>(steam);
        foreach(string root in steam){string file=Path.Combine(root,"steamapps","libraryfolders.vdf");if(!File.Exists(file))continue;
            foreach(Match match in Regex.Matches(File.ReadAllText(file),"\"path\"\\s+\"([^\"]+)\""))libraries.Add(match.Groups[1].Value.Replace("\\\\","\\"));}
        var found=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(string library in libraries){string game=Path.Combine(library,"steamapps","common","StellarBlade");if(Directory.Exists(Path.Combine(game,"SB","Content","Paks")))found.Add(game);}
        if(found.Count==1)foreach(string item in found)return item;
        return "";
    }
    public static Dictionary<string,object> Read(string assets,string output){
        var json=new JavaScriptSerializer();var data=File.Exists(SettingsPath)?json.Deserialize<Dictionary<string,object>>(File.ReadAllText(SettingsPath,Encoding.UTF8)):new Dictionary<string,object>();
        if(!data.ContainsKey("pakRoot")){string game=FindGame();data["pakRoot"]=String.IsNullOrEmpty(game)?"":Path.Combine(game,"SB","Content","Paks");}
        if(!data.ContainsKey("mappings")||!File.Exists(Convert.ToString(data["mappings"])))data["mappings"]=Path.Combine(assets,"Mappings","StellarBlade_1.1.0.usmap");
        data["python"]=Path.Combine(assets,"Runtime","Python","python.exe");
        data["powershell"]=Path.Combine(assets,"Runtime","PowerShell","pwsh.exe");
        data["libraries"]=Path.Combine(output,"Reader");data["nativeRoot"]=data["libraries"];
        return data;
    }
    public static void Save(Dictionary<string,object> data){Directory.CreateDirectory(Folder);File.WriteAllText(SettingsPath,new JavaScriptSerializer().Serialize(data),new UTF8Encoding(false));}
    public static bool Edit(IWin32Window owner,string assets,string output){
        var data=Read(assets,output);var game=new TextBox{Dock=DockStyle.Fill};var mapping=new TextBox{Dock=DockStyle.Fill};
        string paks=Convert.ToString(data["pakRoot"]);if(Directory.Exists(paks))game.Text=Directory.GetParent(paks).Parent.Parent.FullName;
        mapping.Text=Convert.ToString(data["mappings"]);
        using(var form=new Form{Text="Outfit Colours - Settings",Width=830,Height=310,StartPosition=FormStartPosition.CenterParent,MinimizeBox=false,MaximizeBox=false,FormBorderStyle=FormBorderStyle.FixedDialog}){
            var panel=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=3,RowCount=5,Padding=new Padding(12)};
            panel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,140));panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));panel.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,85));
            var browseGame=new Button{Text="Browse...",Dock=DockStyle.Fill};var browseMap=new Button{Text="Browse...",Dock=DockStyle.Fill};
            panel.Controls.Add(new Label{Text="Stellar Blade folder",AutoSize=true},0,0);panel.Controls.Add(game,1,0);panel.Controls.Add(browseGame,2,0);
            panel.Controls.Add(new Label{Text="Game mapping (.usmap)",AutoSize=true},0,1);panel.Controls.Add(mapping,1,1);panel.Controls.Add(browseMap,2,1);
            var help=new Label{Text="The Stellar Blade 1.1.0 mapping is included and selected automatically. Browse only to override it.\r\nThe first preparation downloads asset-reading libraries into your local cache. Internet is required once.\r\nPython, image tools and PowerShell are bundled.",AutoSize=true,MaximumSize=new System.Drawing.Size(770,0),Margin=new Padding(0,15,0,10)};
            panel.Controls.Add(help,0,2);panel.SetColumnSpan(help,3);
            var save=new Button{Text="Save",AutoSize=true};var cancel=new Button{Text="Cancel",AutoSize=true,DialogResult=DialogResult.Cancel};
            var buttons=new FlowLayoutPanel{AutoSize=true,FlowDirection=FlowDirection.RightToLeft,Dock=DockStyle.Fill};buttons.Controls.Add(cancel);buttons.Controls.Add(save);panel.Controls.Add(buttons,0,3);panel.SetColumnSpan(buttons,3);
            browseGame.Click+=(s,e)=>{using(var dialog=new FolderBrowserDialog{Description="Choose StellarBlade, SB, or Content/Paks",SelectedPath=game.Text})if(dialog.ShowDialog(form)==DialogResult.OK){string candidate=dialog.SelectedPath;for(int i=0;i<4;i++){if(Directory.Exists(Path.Combine(candidate,"SB","Content","Paks"))){game.Text=candidate;return;}var parent=Directory.GetParent(candidate);if(parent==null)break;candidate=parent.FullName;}MessageBox.Show(form,"Choose the folder containing SB/Content/Paks.");}};
            browseMap.Click+=(s,e)=>{using(var dialog=new OpenFileDialog{Filter="Game mapping (*.usmap)|*.usmap",Title="Choose the mapping matching your Stellar Blade version"})if(dialog.ShowDialog(form)==DialogResult.OK)mapping.Text=dialog.FileName;};
            save.Click+=(s,e)=>{string target=Path.Combine(game.Text,"SB","Content","Paks");if(!Directory.Exists(target)){MessageBox.Show(form,"Choose a valid Stellar Blade folder first.");return;}if(!String.IsNullOrWhiteSpace(mapping.Text)&&!File.Exists(mapping.Text)){MessageBox.Show(form,"The selected mapping file does not exist.");return;}data["pakRoot"]=target;data["mappings"]=mapping.Text;Save(data);form.DialogResult=DialogResult.OK;form.Close();};
            form.Controls.Add(panel);form.CancelButton=cancel;return form.ShowDialog(owner)==DialogResult.OK;
        }
    }
}
