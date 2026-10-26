using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Diagnostics;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using System.Threading.Tasks;
using System.Reflection;

[assembly: AssemblyTitle("Outfit Colours Preparer")]
[assembly: AssemblyProduct("Outfit Colours Preparer")]
[assembly: AssemblyCompany("")]
[assembly: AssemblyVersion("0.4.10.0")]

class ReversalPreparer : Form {
    readonly string home=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"Assets");
    readonly string output=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"OutfitReversalPrepared");
    readonly JavaScriptSerializer json=new JavaScriptSerializer{MaxJsonLength=32*1024*1024};
    readonly CheckedListBox outfits=new CheckedListBox{Dock=DockStyle.Fill,CheckOnClick=true,IntegralHeight=false};
    readonly TextBox search=new TextBox{Width=300};
    readonly List<Item> inventory=new List<Item>();
    readonly HashSet<string> selectedIds=new HashSet<string>(StringComparer.Ordinal);
    bool filtering,loadingPreferences,busy;
    readonly TextBox log=new TextBox{Multiline=true,ReadOnly=true,Dock=DockStyle.Fill,ScrollBars=ScrollBars.Vertical};
    readonly Button scan=new Button{Text="1. Scan outfits",AutoSize=true,MinimumSize=new Size(130,28)};
    readonly Button prepare=new Button{Text="3. Prepare selected",AutoSize=true,MinimumSize=new Size(160,30)};
    readonly Button uninstall=new Button{Text="Uninstall selected",AutoSize=true,MinimumSize=new Size(140,30)};
    readonly Button install=new Button{Text="4. Install prepared",AutoSize=true,MinimumSize=new Size(150,30)};
    readonly Button open=new Button{Text="Open output",AutoSize=true,MinimumSize=new Size(115,30)};
    readonly Button startGame=new Button{Text="Start Stellar Blade",AutoSize=true,MinimumSize=new Size(140,30)};
    readonly Button showSelected=new Button{Text="Show selected",AutoSize=true};
    readonly TextBox savedDetails=new TextBox{ReadOnly=true,Multiline=true,Dock=DockStyle.Fill,Height=52,ScrollBars=ScrollBars.Vertical};
    bool onlySelected;
    readonly Button setup=new Button{Text="Settings",AutoSize=true};
    readonly Label dependencies=new Label{Text="",AutoSize=false,Height=15,Font=new Font(SystemFonts.MessageBoxFont.FontFamily,8f),Dock=DockStyle.Top,Margin=new Padding(0)};
    readonly FlowLayoutPanel dependencyLinks=new FlowLayoutPanel{Height=15,Font=new Font(SystemFonts.MessageBoxFont.FontFamily,8f),Dock=DockStyle.Bottom,Margin=new Padding(0),WrapContents=false};
    readonly Panel dependencyAdvice=new Panel{Height=32,Dock=DockStyle.Top,Visible=false,Margin=new Padding(0)};
    readonly CheckBox invert=new CheckBox{Text="Disable lightness inversion",AutoSize=true};
    readonly CheckBox skin=new CheckBox{Text="Preserve skin-like texture colours",Checked=true,AutoSize=true};
    readonly ToolTip tips=new ToolTip();
    readonly CheckBox red=new CheckBox{Text="Retain red",AutoSize=true};
    readonly CheckBox gold=new CheckBox{Text="Retain gold",AutoSize=true};
    readonly ComboBox mode=new ComboBox{DropDownStyle=ComboBoxStyle.DropDownList,Width=165};
    readonly CheckBox advancedEnabled=new CheckBox{Text="Enable advanced settings",AutoSize=true};
    readonly NumericUpDown skinStrength=new NumericUpDown{Minimum=0,Maximum=100,Value=50,Width=62};
    readonly NumericUpDown redStrength=new NumericUpDown{Minimum=0,Maximum=100,Value=50,Width=62};
    readonly NumericUpDown goldStrength=new NumericUpDown{Minimum=0,Maximum=100,Value=50,Width=62};
    readonly CheckBox keepPrevious=new CheckBox{Text="Keep previous colour versions of selected outfits",AutoSize=true};
    readonly CheckBox redBlueSwap=new CheckBox{Text="Reverse red and blue (red becomes blue; blue becomes red)",AutoSize=true};
    readonly TableLayoutPanel advancedBody=new TableLayoutPanel{Dock=DockStyle.Top,AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,Visible=false,ColumnCount=1,Padding=new Padding(0,2,0,2),Margin=new Padding(0)};
    readonly Button advancedToggle=new Button{Text="Advanced settings >",AutoSize=true,Margin=new Padding(0,2,0,0)};
    readonly GroupBox optionGroup=new GroupBox{Text="2. Select outfits below and choose colours",Dock=DockStyle.Fill,AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,Padding=new Padding(10,6,10,6)};
    readonly Label skinNote=new Label{Text="Skin colour filter: if reversal has little or no effect, try preparing again with Preserve skin-like texture colours unchecked.",AutoSize=true,Margin=new Padding(3,0,0,3)};
    readonly Label status=new Label{Text="Ready. Start with 1. Scan outfits.",AutoSize=true,Font=new Font(SystemFonts.MessageBoxFont,FontStyle.Bold),Margin=new Padding(0,3,0,3)};
    readonly ProgressBar progress=new ProgressBar{Dock=DockStyle.Fill,Height=9,Minimum=0,Maximum=5,Value=0,Style=ProgressBarStyle.Continuous,Margin=new Padding(0,0,0,4)};
    readonly Label selectionCount=new Label{Text="0 outfits selected",AutoSize=true,Margin=new Padding(16,7,0,0)};
    readonly string preferencePath;
    Dictionary<string,object> settings;
    class Item {public string Id,Name,Modes,Summary,Details;public bool Duplicate,Prepared,Partial,Installed;public override string ToString(){return (String.IsNullOrEmpty(Name)?Id:Name)+"  ["+(Duplicate?"duplicate ID: skipped":Summary??(Prepared?"Prepared":"Not prepared"))+"]";}}
    class PhaseProgress {public string Phase,Message,OutfitName;public int Step,Total,OutfitIndex,OutfitTotal;}
    class ProcessMessage {public string Text;public bool Error;public PhaseProgress Progress;}
    class ProcessResult {public int ExitCode;public Dictionary<string,object> Summary;}

    public ReversalPreparer():this(null){}
    public ReversalPreparer(string preferences){
        LocalSetup.Save(LocalSetup.Read(home,output));
        preferencePath=preferences??Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"OutfitReversalPreparer","Preferences.json");
        Icon=AppIcon.Load();
        Text="Outfit Colours - Prelaunch Preparer 0.4.10";Width=1110;Height=870;MinimumSize=new Size(940,760);AutoScaleMode=AutoScaleMode.Font;
        var root=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=1,RowCount=9,Padding=new Padding(10,8,10,8)};
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));root.RowStyles.Add(new RowStyle(SizeType.AutoSize));root.RowStyles.Add(new RowStyle(SizeType.AutoSize));root.RowStyles.Add(new RowStyle(SizeType.Percent,100));root.RowStyles.Add(new RowStyle(SizeType.AutoSize));root.RowStyles.Add(new RowStyle(SizeType.AutoSize));root.RowStyles.Add(new RowStyle(SizeType.AutoSize));root.RowStyles.Add(new RowStyle(SizeType.Absolute,126));
        var header=new TableLayoutPanel{Dock=DockStyle.Top,ColumnCount=2,AutoSize=false,Height=92,Margin=new Padding(0,0,0,6)};
        header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,49));header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,51));
        var start=new FlowLayoutPanel{Dock=DockStyle.Fill,FlowDirection=FlowDirection.TopDown,WrapContents=false,AutoSize=true,Margin=new Padding(0,0,10,0)};
        start.Controls.Add(new Label{Text="OUTFIT COLOURS",AutoSize=true,Font=new Font(SystemFonts.MessageBoxFont,FontStyle.Bold),Margin=new Padding(0,0,0,5)});
        start.Controls.Add(new Label{Text="Prepare custom CNS outfits before starting the game.",AutoSize=true,Margin=new Padding(0,0,0,5)});
        var scanButtons=new FlowLayoutPanel{AutoSize=true,Margin=new Padding(0)};scanButtons.Controls.AddRange(new Control[]{scan,setup});start.Controls.Add(scanButtons);
        var instructions=new TableLayoutPanel{Dock=DockStyle.Fill,ColumnCount=1,AutoSize=false,Padding=new Padding(10,0,0,0),Margin=new Padding(0)};
        instructions.Controls.Add(new Label{Text="INSTRUCTIONS",AutoSize=true,Font=new Font(SystemFonts.MessageBoxFont,FontStyle.Bold),Margin=new Padding(0,0,0,4)});
        instructions.Controls.Add(new Label{Text="1. Scan.  2. Select outfits and adjust colours.  3. Prepare.\r\n4. Close the game and click Install prepared.\r\nOpen output shows installer assets. Unchecked preparations are retained.",AutoSize=true,Margin=new Padding(0)});
        dependencyAdvice.Controls.Add(dependencies);dependencyAdvice.Controls.Add(dependencyLinks);instructions.Controls.Add(dependencyAdvice);
        header.Controls.Add(start,0,0);header.Controls.Add(instructions,1,0);root.Controls.Add(header,0,0);
        var optionRows=new TableLayoutPanel{Dock=DockStyle.Top,ColumnCount=1,AutoSize=true,AutoSizeMode=AutoSizeMode.GrowAndShrink,Margin=new Padding(0)};
        var colourRow=new FlowLayoutPanel{Dock=DockStyle.Top,AutoSize=true,Margin=new Padding(0,0,0,3)};
        mode.Items.AddRange(new object[]{"Reverse colours","Convert all to white"});mode.SelectedIndex=0;
        colourRow.Controls.AddRange(new Control[]{mode,invert,red,gold});optionRows.Controls.Add(colourRow);
        skin.Margin=new Padding(3,1,0,1);optionRows.Controls.Add(skin);optionRows.Controls.Add(skinNote);optionRows.Controls.Add(advancedToggle);optionRows.Controls.Add(advancedBody);
        advancedEnabled.Margin=new Padding(3,3,0,3);advancedBody.Controls.Add(advancedEnabled);
        var strengths=new FlowLayoutPanel{Dock=DockStyle.Top,AutoSize=true,Margin=new Padding(0)};
        var skinLabel=new Label{Text="Skin preservation (0-100)",AutoSize=true,Margin=new Padding(3,5,2,0)};
        var redLabel=new Label{Text="Retain red (0-100)",AutoSize=true,Margin=new Padding(18,5,2,0)};
        var goldLabel=new Label{Text="Retain gold (0-100)",AutoSize=true,Margin=new Padding(18,5,2,0)};
        strengths.Controls.AddRange(new Control[]{skinLabel,skinStrength,redLabel,redStrength,goldLabel,goldStrength});advancedBody.Controls.Add(strengths);
        advancedBody.Controls.Add(new Label{Text="50 is standard. At 100, maximum skin safety preserves whole materials containing broad skin regions, including clothing that shares them.",AutoSize=true,Margin=new Padding(3,1,0,3)});
        advancedBody.Controls.Add(keepPrevious);advancedBody.Controls.Add(redBlueSwap);advancedBody.Controls.Add(new Label{Text="Red/blue applies to Reverse colours. Retained colours take priority.",AutoSize=true,Margin=new Padding(3,0,0,0)});
        optionGroup.Controls.Add(optionRows);root.Controls.Add(optionGroup,0,1);
        var searchBar=new FlowLayoutPanel{Dock=DockStyle.Fill,AutoSize=true,Padding=new Padding(0,4,0,2),Margin=new Padding(0,1,0,1)};
        var clearSearch=new Button{Text="Clear",AutoSize=true};var all=new Button{Text="Select shown",AutoSize=true};var none=new Button{Text="Deselect all",AutoSize=true};
        searchBar.Controls.AddRange(new Control[]{new Label{Text="Search outfits",AutoSize=true,Margin=new Padding(0,5,8,0)},search,clearSearch,all,none,showSelected});root.Controls.Add(searchBar,0,2);
        outfits.Margin=new Padding(0,1,0,4);root.Controls.Add(outfits,0,3);
        root.RowStyles.Insert(4,new RowStyle(SizeType.Absolute,54));root.Controls.Add(savedDetails,0,4);outfits.HorizontalScrollbar=true;
        var actions=new FlowLayoutPanel{Dock=DockStyle.Fill,AutoSize=true,Margin=new Padding(0,3,0,2)};actions.Controls.AddRange(new Control[]{prepare,install,open,startGame,uninstall,selectionCount});root.Controls.Add(actions,0,5);
        var statusRows=new TableLayoutPanel{Dock=DockStyle.Top,ColumnCount=1,AutoSize=true,Margin=new Padding(0)};statusRows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));statusRows.Controls.Add(status);statusRows.Controls.Add(progress);root.Controls.Add(statusRows,0,6);
        root.Controls.Add(new Label{Text="PROCESS LOG",AutoSize=true,Font=new Font(SystemFonts.MessageBoxFont,FontStyle.Bold),Margin=new Padding(0,2,0,3)},0,7);root.Controls.Add(log,0,8);Controls.Add(root);
        Action setTextWidths=()=>{skinNote.MaximumSize=new Size(Math.Max(600,optionGroup.ClientSize.Width-24),0);status.MaximumSize=new Size(Math.Max(600,ClientSize.Width-30),0);};Resize+=(s,e)=>setTextWidths();setTextWidths();
        tips.SetToolTip(skin,"Known skin materials and exact matching skin assets are always excluded. This extra colour filter protects flesh inside mixed textures and can also retain bronze or tan clothing.");
        tips.SetToolTip(redStrength,"50: standard retention. Higher values include more red shades and highlights. Used only with Retain red and advanced settings enabled.");tips.SetToolTip(goldStrength,"50: standard retention. Higher values include more gold shades and highlights. Used only with Retain gold and advanced settings enabled.");
        tips.SetToolTip(keepPrevious,"Adds another selectable colour version. Unchecked replaces all saved colour versions of the selected outfits. Uninstall selected removes ALL their generated colour versions.");
        tips.SetToolTip(uninstall,"Uninstall ALL generated colour versions of the selected outfits. Original outfits and unselected outfits remain.");
        tips.SetToolTip(all,"Select all outfits in the filtered list. Hidden selections are retained.");tips.SetToolTip(none,"Deselect every outfit, including hidden search results.");
        outfits.ItemCheck+=(s,e)=>{if(filtering)return;var item=(Item)outfits.Items[e.Index];if(item.Duplicate){e.NewValue=CheckState.Unchecked;return;}if(e.NewValue==CheckState.Checked)selectedIds.Add(item.Id);else selectedIds.Remove(item.Id);UpdateSelectionCount();if(onlySelected)BeginInvoke((Action)(()=>FilterInventory()));};
        search.TextChanged+=(s,e)=>FilterInventory();clearSearch.Click+=(s,e)=>search.Clear();LoadPreferences();
        Action refreshAdvanced=()=>{skinStrength.Enabled=advancedEnabled.Checked&&skin.Checked;skinLabel.Enabled=skinStrength.Enabled;redStrength.Enabled=advancedEnabled.Checked&&red.Checked;redLabel.Enabled=redStrength.Enabled;goldStrength.Enabled=advancedEnabled.Checked&&gold.Checked;goldLabel.Enabled=goldStrength.Enabled;keepPrevious.Enabled=advancedEnabled.Checked;redBlueSwap.Enabled=advancedEnabled.Checked&&mode.SelectedIndex==0;invert.Enabled=mode.SelectedIndex==0;};refreshAdvanced();
        advancedToggle.Click+=(s,e)=>{advancedBody.Visible=!advancedBody.Visible;advancedToggle.Text=advancedBody.Visible?"Advanced settings v":"Advanced settings >";};
        foreach(var checkbox in new[]{advancedEnabled,skin,red,gold,redBlueSwap,invert,keepPrevious})checkbox.CheckedChanged+=(s,e)=>{refreshAdvanced();SavePreferences();};foreach(var control in new[]{skinStrength,redStrength,goldStrength})control.ValueChanged+=(s,e)=>SavePreferences();mode.SelectedIndexChanged+=(s,e)=>{refreshAdvanced();SavePreferences();};
        scan.Click+=(s,e)=>Run(new string[]{"--scan"},true);
        uninstall.Click+=(s,e)=>{var chosen=inventory.Where(i=>!i.Duplicate&&i.Prepared&&selectedIds.Contains(i.Id)).ToArray();if(chosen.Length==0){MessageBox.Show(this,"Select at least one prepared outfit to uninstall.","Uninstall selected");return;}if(MessageBox.Show(this,"Are you sure you want to uninstall ALL generated colour versions of the selected outfits?","Uninstall selected",MessageBoxButtons.YesNo,MessageBoxIcon.Warning,MessageBoxDefaultButton.Button2)!=DialogResult.Yes)return;var args=new List<string>{"--uninstall"};foreach(var item in chosen){args.Add("--outfit");args.Add(item.Id);}Run(args.ToArray(),false);};
        prepare.Click+=(s,e)=>{var chosen=inventory.Where(i=>!i.Duplicate&&selectedIds.Contains(i.Id)).ToArray();if(chosen.Length==0){MessageBox.Show("Select at least one outfit after scanning.","Prepare selected");return;}var args=new List<string>();foreach(var item in chosen){args.Add("--outfit");args.Add(item.Id);}AddColourArguments(args);Run(args.ToArray(),false);};
        all.Click+=(s,e)=>{for(int i=0;i<outfits.Items.Count;i++)outfits.SetItemChecked(i,!((Item)outfits.Items[i]).Duplicate);};none.Click+=(s,e)=>{selectedIds.Clear();onlySelected=false;showSelected.Text="Show selected";FilterInventory();};
        showSelected.Click+=(s,e)=>{onlySelected=!onlySelected;showSelected.Text=onlySelected?"Show all":"Show selected";search.Clear();FilterInventory();};
        outfits.SelectedIndexChanged+=(s,e)=>{var item=outfits.SelectedItem as Item;savedDetails.Text=item==null?"Select an outfit to see its saved preparation settings.":item.Name+Environment.NewLine+(item.Details??"No saved settings.").Replace("\n",Environment.NewLine);};
        startGame.Click+=(s,e)=>{try{var config=LocalSetup.Read(home,output);string game=Directory.GetParent(Convert.ToString(config["pakRoot"])).Parent.Parent.FullName;string uri=LocalSetup.SteamLaunchUri(game);if(uri==null)throw new Exception("Could not find the Steam manifest for the selected game folder. Launch Stellar Blade from Steam.");Process.Start(new ProcessStartInfo(uri){UseShellExecute=true});}catch(Exception error){MessageBox.Show(error.Message,"Start Stellar Blade");}};
        install.Click+=(s,e)=>InstallPrepared();
        open.Click+=(s,e)=>{try{string folder=Path.Combine(output,"Install","Assets");if(!Directory.Exists(folder))throw new Exception("Prepare outfits first to create the installer assets.");Process.Start(new ProcessStartInfo("explorer.exe",Quote(folder)){UseShellExecute=true});}catch(Exception error){MessageBox.Show(error.Message,"Open output");}};
        setup.Click+=(s,e)=>LocalSetup.Edit(this,home,output);
        FormClosing+=(s,e)=>{if(busy){e.Cancel=true;MessageBox.Show("The current process is still running. Wait for its completion status before closing.","Process running");}};
        SetBusy(false);
    }
    void AddColourArguments(List<string> args){
        args.Add("--mode");args.Add(mode.SelectedIndex==1?"white":"reverse");if(invert.Checked)args.Add("--disable-lightness-inversion");if(!skin.Checked)args.Add("--no-protect-skin");if(red.Checked)args.Add("--retain-red");if(gold.Checked)args.Add("--retain-gold");
        if(advancedEnabled.Checked){if(keepPrevious.Checked)args.Add("--keep-previous");if(skin.Checked){args.Add("--skin-strength");args.Add(((int)skinStrength.Value).ToString(System.Globalization.CultureInfo.InvariantCulture));}if(red.Checked){args.Add("--red-strength");args.Add(((int)redStrength.Value).ToString(System.Globalization.CultureInfo.InvariantCulture));}if(gold.Checked){args.Add("--gold-strength");args.Add(((int)goldStrength.Value).ToString(System.Globalization.CultureInfo.InvariantCulture));}if(redBlueSwap.Checked&&mode.SelectedIndex==0)args.Add("--red-blue-swap");}
    }
    void LoadPreferences(){
        loadingPreferences=true;try{if(!File.Exists(preferencePath))return;var p=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(preferencePath,Encoding.UTF8));if(p==null)return;
            foreach(var pair in new[]{new KeyValuePair<string,NumericUpDown>("skinStrength",skinStrength),new KeyValuePair<string,NumericUpDown>("redStrength",redStrength),new KeyValuePair<string,NumericUpDown>("goldStrength",goldStrength)})if(p.ContainsKey(pair.Key))pair.Value.Value=Math.Max(0,Math.Min(100,Convert.ToInt32(p[pair.Key])));
            foreach(var pair in new[]{new KeyValuePair<string,CheckBox>("keepPrevious",keepPrevious),new KeyValuePair<string,CheckBox>("advancedEnabled",advancedEnabled),new KeyValuePair<string,CheckBox>("preserveSkin",skin),new KeyValuePair<string,CheckBox>("disableLightness",invert),new KeyValuePair<string,CheckBox>("retainRed",red),new KeyValuePair<string,CheckBox>("retainGold",gold),new KeyValuePair<string,CheckBox>("redBlueSwap",redBlueSwap)})if(p.ContainsKey(pair.Key))pair.Value.Checked=Convert.ToBoolean(p[pair.Key]);if(p.ContainsKey("mode"))mode.SelectedIndex=Convert.ToString(p["mode"])=="white"?1:0;
        }catch(Exception error){Append("Could not load preferences; check settings before preparing: "+error.Message);}finally{loadingPreferences=false;}
    }
    void SavePreferences(){if(loadingPreferences)return;try{Directory.CreateDirectory(Path.GetDirectoryName(preferencePath));var p=new Dictionary<string,object>{{"keepPrevious",keepPrevious.Checked},{"advancedEnabled",advancedEnabled.Checked},{"skinStrength",(int)skinStrength.Value},{"redStrength",(int)redStrength.Value},{"goldStrength",(int)goldStrength.Value},{"redBlueSwap",redBlueSwap.Checked},{"preserveSkin",skin.Checked},{"disableLightness",invert.Checked},{"retainRed",red.Checked},{"retainGold",gold.Checked},{"mode",mode.SelectedIndex==1?"white":"reverse"}};string temporary=preferencePath+".tmp";File.WriteAllText(temporary,json.Serialize(p),Encoding.UTF8);if(File.Exists(preferencePath))File.Replace(temporary,preferencePath,null);else File.Move(temporary,preferencePath);}catch(Exception error){Append("Could not save preferences: "+error.Message);}}
    static string Quote(string text){return "\""+text.Replace("\"","\\\"")+"\"";}
    void ShowDependencies(string text){
        dependencyAdvice.Visible=false;dependencies.Text="";dependencyLinks.Controls.Clear();
        var data=json.Deserialize<Dictionary<string,object>>(text);object value;if(!data.TryGetValue("dependencies",out value))return;var check=value as Dictionary<string,object>;if(check==null||!check.TryGetValue("items",out value))return;var rows=value as IEnumerable;if(rows==null)return;
        var labels=new List<string>();var details=new List<string>();bool advice=false;
        foreach(var raw in rows){var row=raw as Dictionary<string,object>;if(row==null)continue;string state=Convert.ToString(row["state"]),name=Convert.ToString(row["name"]),version=Convert.ToString(row["version"]);if(state=="ok")continue;advice=true;labels.Add(name+": "+(state=="missing"?"install required":state=="incomplete"?"complete installation required":state=="update"?"update required ("+version+")":"version unverified - check/update"));details.Add(Convert.ToString(row["message"]));string url=name=="CNS"?"https://www.nexusmods.com/stellarblade/mods/1496":"https://www.nexusmods.com/stellarblade/mods/2952";var link=new LinkLabel{Text=name+" mod page",AutoSize=true,Margin=new Padding(0,0,12,0)};link.LinkClicked+=(s,e)=>{try{Process.Start(new ProcessStartInfo(url){UseShellExecute=true});}catch(Exception error){MessageBox.Show(error.Message,"Open mod page");}};dependencyLinks.Controls.Add(link);}
        dependencies.Text=String.Join("; ",labels);dependencies.ForeColor=Color.DarkOrange;tips.SetToolTip(dependencies,String.Join(Environment.NewLine,details));dependencyAdvice.Visible=advice;
    }
    static Item[] ReadInventory(string text){
        var document=new JavaScriptSerializer{MaxJsonLength=32*1024*1024}.Deserialize<Dictionary<string,object>>(text);object value;if(document==null||!document.TryGetValue("outfits",out value))throw new FormatException("Inventory is missing the outfits list. Run Scan outfits again.");var rows=value as IEnumerable;if(rows==null||value is string||value is IDictionary)throw new FormatException("Inventory outfits must be a JSON array.");var result=new List<Item>();
        foreach(var raw in rows){var row=raw as Dictionary<string,object>;if(row==null||!row.ContainsKey("id")||!row.ContainsKey("duplicate"))throw new FormatException("Inventory contains an invalid outfit entry.");var modes=new List<string>();object rawModes;if(row.TryGetValue("preparedModes",out rawModes)&&rawModes is IEnumerable&&!(rawModes is string))foreach(var entry in (IEnumerable)rawModes)modes.Add(Convert.ToString(entry)=="white"?"White":"Reverse");result.Add(new Item{Id=Convert.ToString(row["id"]),Name=row.ContainsKey("name")?Convert.ToString(row["name"]):null,Duplicate=Convert.ToBoolean(row["duplicate"]),Prepared=row.ContainsKey("prepared")&&Convert.ToBoolean(row["prepared"]),Modes=String.Join(" + ",modes),Partial=row.ContainsKey("partial")&&Convert.ToBoolean(row["partial"]),Installed=row.ContainsKey("installed")&&Convert.ToBoolean(row["installed"]),Summary=row.ContainsKey("preparationSummary")?Convert.ToString(row["preparationSummary"]):null,Details=row.ContainsKey("preparationDetails")?Convert.ToString(row["preparationDetails"]):null});}
        return result.OrderBy(item=>String.IsNullOrEmpty(item.Name)?item.Id:item.Name,StringComparer.OrdinalIgnoreCase).ThenBy(item=>item.Id,StringComparer.Ordinal).ToArray();
    }
    void FilterInventory(){filtering=true;outfits.BeginUpdate();try{outfits.Items.Clear();string query=search.Text.Trim();foreach(var item in inventory)if((!onlySelected||selectedIds.Contains(item.Id))&&(query.Length==0||item.Id.IndexOf(query,StringComparison.OrdinalIgnoreCase)>=0||(!String.IsNullOrEmpty(item.Name)&&item.Name.IndexOf(query,StringComparison.OrdinalIgnoreCase)>=0)))outfits.Items.Add(item,!item.Duplicate&&selectedIds.Contains(item.Id));}finally{outfits.EndUpdate();filtering=false;UpdateSelectionCount();}}
    void UpdateSelectionCount(){selectionCount.Text=selectedIds.Count+" outfit"+(selectedIds.Count==1?"":"s")+" selected";}
    void Append(string message){if(IsDisposed)return;if(InvokeRequired){BeginInvoke((Action)(()=>Append(message)));return;}log.AppendText(message+Environment.NewLine);}
    void SetStatus(string message,Color colour){status.Text=message;status.ForeColor=colour;}
    bool CurrentOutput(){try{var data=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(output,"Install","Assets","InstallManifest.json")));return data.ContainsKey("containerProfile")&&Convert.ToString(data["containerProfile"])=="stellarblade-initial-single-export-v1";}catch{return false;}}
    void SetBusy(bool value){busy=value;scan.Enabled=prepare.Enabled=uninstall.Enabled=setup.Enabled=startGame.Enabled=!value;install.Enabled=!value&&CurrentOutput()&&File.Exists(Path.Combine(output,"Install","InstallPrepared.exe"));open.Enabled=!value&&Directory.Exists(Path.Combine(output,"Install","Assets"));optionGroup.Enabled=outfits.Enabled=search.Parent.Enabled=!value;}
    async void InstallPrepared(){
        if(busy)return;
        try{
            string exe=Path.Combine(output,"Install","InstallPrepared.exe");if(!File.Exists(exe))throw new Exception("Prepare outfits before installing.");
            var config=LocalSetup.Read(home,output);string paks=Convert.ToString(config["pakRoot"]);if(!Directory.Exists(paks))throw new Exception("Choose the game folder in Settings first.");
            string game=Directory.GetParent(paks).Parent.Parent.FullName;
            SetBusy(true);SetStatus("INSTALLING - checking and backing up prepared files...",Color.FromArgb(25,75,140));Append("INSTALLATION STARTED");
            int code=await Task.Run(()=>{using(var process=new Process()){
                process.StartInfo=new ProcessStartInfo(exe,"--game-root "+Quote(game)+" --install"){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true};
                DataReceivedEventHandler receive=(s,e)=>{if(e.Data!=null)BeginInvoke((Action)(()=>Append(e.Data)));};process.OutputDataReceived+=receive;process.ErrorDataReceived+=receive;
                process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();process.WaitForExit();return process.ExitCode;
            }});
            if(code!=0)throw new Exception("Installation did not complete. See the process log for the reason.");
            SetStatus("INSTALLATION COMPLETE - You can start the game.",Color.ForestGreen);
            foreach(var item in inventory)if(item.Prepared){item.Installed=true;item.Summary=(item.Summary??"Prepared").Replace("Prepared (not installed)","Installed").Replace("prepared (not installed)","installed");item.Details=(item.Details??"").Replace("Prepared (not installed)","Installed");}FilterInventory();
        }catch(Exception error){SetStatus("INSTALLATION DID NOT COMPLETE - "+error.Message,Color.Firebrick);Append("ERROR: "+error.Message);}
        finally{SetBusy(false);}
    }
    static bool TryProgress(string line,out PhaseProgress update){
        update=null;if(!line.StartsWith("[PROGRESS] ",StringComparison.Ordinal))return false;try{var p=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(line.Substring(11));int step=Convert.ToInt32(p["step"]),total=Convert.ToInt32(p["total"]);string message=Convert.ToString(p["message"]);if(total<1||total>100||step<1||step>total||String.IsNullOrWhiteSpace(message))return false;update=new PhaseProgress{Step=step,Total=total,Phase=p.ContainsKey("phase")?Convert.ToString(p["phase"]):"",Message=message};if(p.ContainsKey("outfitIndex")&&p.ContainsKey("outfitTotal")){int index=Convert.ToInt32(p["outfitIndex"]),count=Convert.ToInt32(p["outfitTotal"]);if(index>0&&index<=count){update.OutfitIndex=index;update.OutfitTotal=count;update.OutfitName=p.ContainsKey("outfitName")?Convert.ToString(p["outfitName"]):"";}}return true;}catch{return false;}
    }
    void ApplyProgress(PhaseProgress update){string detail=(update.Phase=="scan"?"Scan phase ":"Preparation phase ")+update.Step+" of "+update.Total+" - "+update.Message;if(update.OutfitTotal>0)detail+=" | Outfit "+update.OutfitIndex+" of "+update.OutfitTotal+(String.IsNullOrEmpty(update.OutfitName)?"":": "+update.OutfitName);progress.Style=ProgressBarStyle.Continuous;progress.Maximum=update.Total;progress.Value=update.Step-1;SetStatus(detail,Color.FromArgb(25,75,140));Append(detail);}
    static string PreparationCountMessage(Dictionary<string,object> summary){int updated=((IEnumerable)summary["updatedOutfits"]).Cast<object>().Count();int retained=Math.Max(0,Convert.ToInt32(summary["preparedOutfits"])-updated);return "PREPARATION COMPLETE - "+updated+" outfit"+(updated==1?"":"s")+" updated, "+retained+" retained. Ready to install.";}
    static string ValidatePreparedResult(Dictionary<string,object> summary,string outputFolder){
        if(summary==null||!summary.ContainsKey("success")||!(summary["success"] is bool)||(bool)summary["success"]!=true)throw new FormatException("The process did not report a successful preparation.");string install=Path.GetFullPath(Path.Combine(outputFolder,"Install"));if(!summary.ContainsKey("installFolder")||!String.Equals(install.TrimEnd(Path.DirectorySeparatorChar),Path.GetFullPath(Convert.ToString(summary["installFolder"])).TrimEnd(Path.DirectorySeparatorChar),StringComparison.OrdinalIgnoreCase))throw new FormatException("The completed output location does not match this preparer's output.");if(!summary.ContainsKey("preparedOutfits")||Convert.ToInt32(summary["preparedOutfits"])<1)throw new FormatException("No successfully prepared outfits were reported.");if(!File.Exists(Path.Combine(install,"InstallPrepared.exe"))||!File.Exists(Path.Combine(install,"Assets","Install-Prepared.ps1")))throw new FileNotFoundException("The completed installer scripts were not found.");
        var manifest=new JavaScriptSerializer{MaxJsonLength=32*1024*1024}.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(install,"Assets","InstallManifest.json"),Encoding.UTF8));object rawFiles;if(manifest==null||!manifest.TryGetValue("files",out rawFiles)||!(rawFiles is IEnumerable)||rawFiles is string||rawFiles is IDictionary)throw new FormatException("The completed install manifest has no valid file list.");int count=0;
        foreach(var raw in (IEnumerable)rawFiles){var file=raw as Dictionary<string,object>;if(file==null||!file.ContainsKey("relativePath"))throw new FormatException("The completed install manifest contains an invalid entry.");string relative=Convert.ToString(file["relativePath"]);string path=Path.GetFullPath(Path.Combine(install,"Assets",relative.Replace('/',Path.DirectorySeparatorChar)));if(String.IsNullOrWhiteSpace(relative)||Path.IsPathRooted(relative)||!path.StartsWith(install+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)||!File.Exists(path))throw new FileNotFoundException("A completed install file is missing or outside its output folder: "+relative);count++;}if(count==0)throw new FormatException("The completed install manifest is empty.");return install;
    }
    void Run(string[] extra,bool isScan){if(busy)return;bool isUninstall=extra.Contains("--uninstall");try{
        settings=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(LocalSetup.SettingsPath,Encoding.UTF8));string python=Path.Combine(home,"Runtime","Python","python.exe");if(!File.Exists(python))throw new Exception("Bundled Python is missing. Extract the entire ZIP with Assets beside the EXE.");if(!settings.ContainsKey("pakRoot")||!Directory.Exists(Convert.ToString(settings["pakRoot"]))){if(!LocalSetup.Edit(this,home,output))return;settings=LocalSetup.Read(home,output);}if(!isScan&&!isUninstall&&(!settings.ContainsKey("mappings")||!File.Exists(Convert.ToString(settings["mappings"])))){if(!LocalSetup.Edit(this,home,output))return;settings=LocalSetup.Read(home,output);if(!File.Exists(Convert.ToString(settings["mappings"])))throw new Exception("Choose the matching Stellar Blade .usmap in Settings before preparing outfits.");}Directory.CreateDirectory(output);SetBusy(true);progress.Style=ProgressBarStyle.Marquee;progress.MarqueeAnimationSpeed=30;SetStatus(isUninstall?"UNINSTALLING - checking selected outfits and backups...":isScan?"Scanning outfits - waiting for results...":"Starting preparation - waiting for phase 1 of 5...",Color.FromArgb(25,75,140));Append(Environment.NewLine+(isUninstall?"UNINSTALL STARTED":isScan?"SCAN STARTED":"PREPARATION STARTED"));
        var args=new List<string>{"-u","-B",Path.Combine(home,"prep.py"),"--settings",LocalSetup.SettingsPath,"--output",output};args.AddRange(extra);var worker=new BackgroundWorker{WorkerReportsProgress=true};
        worker.DoWork+=(s,e)=>{var result=new ProcessResult{ExitCode=-1};using(var process=new Process()){
            process.StartInfo=new ProcessStartInfo(python,String.Join(" ",args.Select(Quote))){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,WorkingDirectory=home};
            process.OutputDataReceived+=(o,a)=>{if(a.Data==null)return;PhaseProgress update;if(TryProgress(a.Data,out update)){worker.ReportProgress(0,new ProcessMessage{Progress=update});return;}try{if(a.Data.StartsWith("{",StringComparison.Ordinal)){var p=new JavaScriptSerializer{MaxJsonLength=32*1024*1024}.Deserialize<Dictionary<string,object>>(a.Data);if(p!=null&&p.ContainsKey("success"))result.Summary=p;}}catch{}worker.ReportProgress(0,new ProcessMessage{Text=a.Data});};
            process.ErrorDataReceived+=(o,a)=>{if(a.Data!=null)worker.ReportProgress(0,new ProcessMessage{Text=a.Data,Error=true});};process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();process.WaitForExit();result.ExitCode=process.ExitCode;
        }e.Result=result;};
        worker.ProgressChanged+=(s,e)=>{var message=(ProcessMessage)e.UserState;if(message.Progress!=null)ApplyProgress(message.Progress);else Append(message.Text);};
        worker.RunWorkerCompleted+=(s,e)=>{SetBusy(false);progress.Style=ProgressBarStyle.Continuous;try{
            if(e.Error!=null)throw new Exception(e.Error.Message,e.Error);var result=(ProcessResult)e.Result;if(result.ExitCode!=0)throw new Exception((isUninstall?"Uninstall":isScan?"Scan":"Preparation")+" stopped (exit "+result.ExitCode+"). Read the process log and output-folder logs.");
            ShowDependencies(File.ReadAllText(Path.Combine(output,"inventory.json"),Encoding.UTF8));
            if(isUninstall){if(result.Summary==null||!result.Summary.ContainsKey("success")||!Convert.ToBoolean(result.Summary["success"])||!result.Summary.ContainsKey("uninstalledOutfits"))throw new Exception("Uninstall did not report success. See the process log.");inventory.Clear();inventory.AddRange(ReadInventory(File.ReadAllText(Path.Combine(output,"inventory.json"),Encoding.UTF8)));FilterInventory();progress.Maximum=1;progress.Value=1;SetStatus("UNINSTALL COMPLETE - ALL generated colour versions of selected outfits removed. Original outfits remain available.",Color.ForestGreen);Append("UNINSTALL COMPLETE. Other installed preparations and their settings were preserved.");}
            else if(isScan){var items=ReadInventory(File.ReadAllText(Path.Combine(output,"inventory.json"),Encoding.UTF8));inventory.Clear();inventory.AddRange(items);selectedIds.RemoveWhere(id=>!inventory.Any(item=>item.Id==id&&!item.Duplicate));FilterInventory();progress.Maximum=1;progress.Value=1;SetStatus("SCAN COMPLETE - Found "+inventory.Count+" custom outfits. Select outfits and colours, then use 3. Prepare selected.",Color.ForestGreen);Append("Found "+inventory.Count+" custom EVE body outfit entries ("+outfits.Items.Count+" shown).");}
            else{string install=ValidatePreparedResult(result.Summary,output);inventory.Clear();inventory.AddRange(ReadInventory(File.ReadAllText(Path.Combine(output,"inventory.json"),Encoding.UTF8)));FilterInventory();progress.Maximum=5;progress.Value=5;SetStatus(PreparationCountMessage(result.Summary),Color.ForestGreen);Append("PREPARATION COMPLETE. Prepared output verified at "+install+". Close the game before clicking Install prepared.");}
        }catch(Exception error){progress.Value=0;SetStatus((isUninstall?"UNINSTALL":isScan?"SCAN":"PREPARATION")+" DID NOT COMPLETE - "+error.Message,Color.Firebrick);Append("ERROR: "+error.Message);}finally{worker.Dispose();}};worker.RunWorkerAsync();
    }catch(Exception error){SetBusy(false);progress.Style=ProgressBarStyle.Continuous;progress.Value=0;SetStatus("COULD NOT START - "+error.Message,Color.Firebrick);Append("ERROR: "+error.Message);MessageBox.Show(error.Message,"Preparer");}}
    [STAThread]static int Main(string[] args){
        try{if(args.Length>0){if(args[0]!="--headless")throw new ArgumentException("Use --headless followed by preparation arguments.");string home=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"Assets");var forwarded=new List<string>{"-u","-B",Path.Combine(home,"prep.py")};forwarded.AddRange(args.Skip(1));using(var process=new Process()){process.StartInfo=new ProcessStartInfo(Path.Combine(home,"Runtime","Python","python.exe"),String.Join(" ",forwarded.Select(Quote))){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,WorkingDirectory=home};process.StartInfo.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"]="1";process.OutputDataReceived+=(s,e)=>{if(e.Data!=null)Console.WriteLine(e.Data);};process.ErrorDataReceived+=(s,e)=>{if(e.Data!=null)Console.Error.WriteLine(e.Data);};process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();process.WaitForExit();return process.ExitCode;}}
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new ReversalPreparer());return 0;}catch(Exception error){if(args.Length>0)Console.Error.WriteLine(error.Message);else MessageBox.Show(error.Message,"Outfit Colours");return 1;}}

}

