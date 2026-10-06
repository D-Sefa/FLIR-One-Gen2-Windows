package com.dsefa.flir;

import android.app.*;
import android.content.*;
import android.hardware.usb.*;
import android.os.*;
import android.graphics.Bitmap;
import android.net.Uri;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import java.text.SimpleDateFormat;

public final class MainActivity extends Activity implements UsbCamera.Listener {
    private static final String USB_PERMISSION="com.dsefa.flir.USB_PERMISSION";
    private static final int SAVE_PNG=20,IMPORT_RAW=21,EXPORT_RAW=22;
    private UsbManager usb;private UsbCamera camera;private TextView status,stats;
    private ThermalView thermal;private GraphView graph;private final Handler ui=new Handler(Looper.getMainLooper());
    private final AtomicReference<RawArchive.Sample> latest=new AtomicReference<>();
    private volatile RawRecorder recorder;private File recordingFile,exportFile;
    private final Map<File,RawRecorder> archiveWriters=new HashMap<>();
    private final Generation cameraGeneration=new Generation(),replayGeneration=new Generation();
    private Bitmap pendingSnapshot;private Button recordButton,freezeButton,playButton;
    private boolean active,frozen,replaying,playing,graphPaused;
    private RawArchive.Reader replayReader;private long previousReplay;
    private final Deque<Long> times=new ArrayDeque<>();private long lastReceived;
    private String connectionMessage="Turn on the camera and connect its USB data cable through OTG";
    private boolean permissionPending;
    private final BroadcastReceiver receiver=new BroadcastReceiver(){public void onReceive(Context context,Intent intent){
        if(USB_PERMISSION.equals(intent.getAction())){permissionPending=false;
            if(intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED,false))connect();else status("USB permission denied. Tap Connect to retry.");}
        else if(UsbManager.ACTION_USB_DEVICE_DETACHED.equals(intent.getAction())){
            UsbDevice d=intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
            if(d!=null&&d.getVendorId()==0x09CB&&d.getProductId()==0x1996){stopCamera();status("Camera disconnected — reconnect USB");}}
        else if(UsbManager.ACTION_USB_DEVICE_ATTACHED.equals(intent.getAction()))connect();
    }};
    protected void onCreate(Bundle state){super.onCreate(state);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        usb=(UsbManager)getSystemService(USB_SERVICE);buildUi();
        IntentFilter filter=new IntentFilter(USB_PERMISSION);filter.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);filter.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
        if(Build.VERSION.SDK_INT>=33)registerReceiver(receiver,filter,Context.RECEIVER_NOT_EXPORTED);else registerReceiver(receiver,filter);
    }
    protected void onStart(){super.onStart();active=true;connect();ui.post(refresh);}
    protected void onStop(){active=false;ui.removeCallbacks(refresh);stopCamera();stopRecording();playing=false;replayGeneration.advance();super.onStop();}
    protected void onDestroy(){unregisterReceiver(receiver);closeReplay();super.onDestroy();}
    protected void onNewIntent(Intent i){super.onNewIntent(i);setIntent(i);if(active)connect();}
    private int dp(int n){return (int)(n*getResources().getDisplayMetrics().density+.5f);}
    private LinearLayout row(LinearLayout parent){LinearLayout r=new LinearLayout(this);r.setOrientation(LinearLayout.HORIZONTAL);parent.addView(r);return r;}
    private Button button(LinearLayout parent,String label,Runnable action){Button b=new Button(this);b.setText(label);b.setTextSize(12);b.setMinHeight(dp(38));parent.addView(b,new LinearLayout.LayoutParams(0,dp(44),1));b.setOnClickListener(v->action.run());return b;}
    private void buildUi(){
        LinearLayout root=new LinearLayout(this);root.setOrientation(1);root.setBackgroundColor(0xff101319);root.setPadding(dp(6),dp(6),dp(6),dp(6));setContentView(root);
        root.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(dp(6)+insets.getSystemWindowInsetLeft(),dp(6)+insets.getSystemWindowInsetTop(),dp(6)+insets.getSystemWindowInsetRight(),dp(6)+insets.getSystemWindowInsetBottom());return insets;});
        TextView title=new TextView(this);title.setText("FLIR ONE Gen 2 · Thermal Analysis");title.setTextSize(19);title.setTextColor(0xffeeeeee);root.addView(title);
        status=new TextView(this);status.setTextColor(0xff82d89d);status.setTextSize(12);root.addView(status);
        thermal=new ThermalView(this);root.addView(thermal,new LinearLayout.LayoutParams(-1,0,1));
        stats=new TextView(this);stats.setTextColor(0xffbbbbcc);stats.setTextSize(11);root.addView(stats);
        LinearLayout controls=row(root);button(controls,"Connect",()->{stopCamera();connect();});
        button(controls,"Rotate",()->{thermal.settings.rotation=(thermal.settings.rotation+90)%360;thermal.refresh();saveSettings();});
        button(controls,"Mirror",()->{thermal.settings.mirror=!thermal.settings.mirror;thermal.refresh();saveSettings();});
        button(controls,"Settings",this::settings);
        LinearLayout capture=row(root);freezeButton=button(capture,"Freeze",()->{frozen=!frozen;freezeButton.setText(frozen?"Resume":"Freeze");});
        button(capture,"PNG",this::savePng);recordButton=button(capture,"Record RAW",this::toggleRecording);button(capture,"Recordings",this::recordings);
        graph=new GraphView(this);root.addView(graph,new LinearLayout.LayoutParams(-1,dp(130)));
        LinearLayout graphButtons=row(root);button(graphButtons,"Pause graph",()->{graphPaused=!graphPaused;graph.pause(graphPaused);});
        button(graphButtons,"− Zoom",()->graph.zoom(2));button(graphButtons,"+ Zoom",()->graph.zoom(.5));button(graphButtons,"Clear pins",()->{thermal.clearPoints();graph.clear();});
        LinearLayout replay=row(root);playButton=button(replay,"Play / Pause",()->{if(replaying){replayGeneration.advance();playing=!playing;if(playing)nextReplay();}});
        button(replay,"Import RAW",()->{Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("application/octet-stream").addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,IMPORT_RAW);});
        button(replay,"Live",()->{closeReplay();replaying=false;playing=false;graph.clear();connect();});
        thermal.listener=p->graph.clear();loadSettings();
    }
    private void connect(){if(!active||replaying||camera!=null)return;
        if(!getPackageManager().hasSystemFeature("android.hardware.usb.host")){status("This phone does not support USB host / OTG");return;}
        UsbDevice found=null;for(UsbDevice d:usb.getDeviceList().values())if(d.getVendorId()==0x09CB&&d.getProductId()==0x1996){found=d;break;}
        if(found==null){status("Camera not found — turn it on and connect USB OTG");return;}
        if(!usb.hasPermission(found)){if(!permissionPending){permissionPending=true;
            PendingIntent pi=PendingIntent.getBroadcast(this,0,new Intent(USB_PERMISSION).setPackage(getPackageName()),PendingIntent.FLAG_MUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
            usb.requestPermission(found,pi);status("Accept Android's USB access permission");}return;}
        final int generation=cameraGeneration.current();
        camera=new UsbCamera(usb,found,new UsbCamera.Listener(){
            public void status(String message){ui.post(()->cameraGeneration.runIfCurrent(generation,()->{
                if(active){connectionMessage=message;status.setText(message);}}));}
            public void frame(int[] r,long t,byte[] jpg,byte[] meta){cameraGeneration.runIfCurrent(generation,()->{
                if(active)MainActivity.this.frame(r,t,jpg,meta);});}
        });camera.start();
    }
    private void stopCamera(){cameraGeneration.advance();if(camera!=null){camera.close();camera=null;}latest.set(null);times.clear();lastReceived=0;}
    public void status(String s){ui.post(()->{if(active){connectionMessage=s;status.setText(s);}});}
    public void frame(int[] raw,long timestamp,byte[] jpeg,byte[] metadata){RawArchive.Sample s=new RawArchive.Sample();s.raw=raw;s.timestamp=timestamp;
        latest.set(s);RawRecorder r=recorder;if(r!=null&&!r.offer(raw,timestamp))status("Recording storage cannot keep up — a RAW frame was dropped");}
    private final Runnable refresh=new Runnable(){public void run(){if(!active)return;
        RawArchive.Sample s=latest.getAndSet(null);if(s!=null&&!replaying){lastReceived=System.currentTimeMillis();times.addLast(lastReceived);
            while(!times.isEmpty()&&times.getFirst()<lastReceived-2000)times.removeFirst();
            // Freeze holds the display only; measurement/RAW recording continues.
            if(!frozen)thermal.frame(s.raw,s.timestamp);
            double[] t=Thermal.temperatures(s.raw,thermal.settings);List<Integer> pins=thermal.points();double[] values=new double[pins.size()];
            for(int n=0;n<values.length;n++)values[n]=t[pins.get(n)];graph.add(s.timestamp,values);
            double fps=times.size()>1?(times.size()-1)*1000./Math.max(1,lastReceived-times.getFirst()):0;
            stats.setText(String.format(Locale.US,"%.1f FPS · 160×120 RAW · %s%s",fps,new SimpleDateFormat("HH:mm:ss",Locale.US).format(new Date(s.timestamp)),recorder!=null?" · recording":""));
            status.setText("Thermal stream active"+(frozen?" · image frozen":"")+" · visible stream unverified");
        }else if(!replaying&&lastReceived>0&&System.currentTimeMillis()-lastReceived>2500){status.setText("No fresh frame for "+(System.currentTimeMillis()-lastReceived)/1000+"s · "+connectionMessage);}
        ui.postDelayed(this,35);
    }};
    private void savePng(){if(thermal.raw()==null){status("No frame to save");return;}pendingSnapshot=thermal.snapshot();
        Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("image/png").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE,"FLIR-"+dateName()+".png");startActivityForResult(i,SAVE_PNG);}
    private String dateName(){return new SimpleDateFormat("yyyy-MM-dd_HH-mm-ss",Locale.US).format(new Date());}
    private File archiveDir(){File f=new File(getFilesDir(),"recordings");f.mkdirs();return f;}
    private void toggleRecording(){if(recorder!=null){stopRecording();return;}if(replaying){status("Return to Live before recording");return;}
        recordingFile=new File(archiveDir(),"FLIR-"+dateName()+"-"+UUID.randomUUID().toString().substring(0,8)+".f1raw");
        try{recorder=new RawRecorder(recordingFile,this::status);archiveWriters.put(recordingFile,recorder);recordButton.setText("Stop RAW");}
        catch(IOException e){status("Cannot record: "+e.getMessage());}}
    private void stopRecording(){RawRecorder r=recorder;recorder=null;if(r!=null)r.close();if(recordButton!=null)recordButton.setText("Record RAW");}
    private void recordings(){File[] files=archiveDir().listFiles((dir,name)->name.endsWith(".f1raw"));
        if(files==null||files.length==0){status("No RAW recordings yet. Tap Record RAW to create one.");return;}
        Arrays.sort(files,Comparator.comparing(File::getName).reversed());String[] names=new String[files.length];
        for(int i=0;i<files.length;i++)names[i]=files[i].getName()+" · "+String.format(Locale.US,"%.1f MB",files[i].length()/1048576.);
        new AlertDialog.Builder(this).setTitle("Recordings · newest first").setItems(names,(dialog,index)->{
            File f=files[index];RawRecorder writer=archiveWriters.get(f);
            if(writer!=null&&!writer.complete()){if(writer==recorder)stopRecording();status("Recording is finishing; open it again shortly");return;}
            new AlertDialog.Builder(this).setTitle(f.getName()).setItems(new String[]{"Play RAW with current display controls","Export original RAW"},(a,b)->{
                if(b==0){
                    try{openReplay(new FileInputStream(f));}catch(IOException e){status(e.getMessage());}}
                else{exportFile=f;Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/octet-stream").putExtra(Intent.EXTRA_TITLE,f.getName()).addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,EXPORT_RAW);}
            }).show();}).show();}
    private void closeReplay(){replayGeneration.advance();playing=false;if(replayReader!=null)try{replayReader.close();}catch(IOException ignored){}replayReader=null;}
    private void openReplay(InputStream stream)throws IOException{stopRecording();stopCamera();closeReplay();replayReader=new RawArchive.Reader(stream);replaying=true;playing=true;previousReplay=0;graph.clear();nextReplay();}
    private void nextReplay(){if(!active||!replaying||!playing||replayReader==null)return;
        try{RawArchive.Sample s=replayReader.next();if(s==null){playing=false;status.setText("Recording ended — tap Live to reconnect");return;}
            long delay=previousReplay==0?1:Math.max(1,Math.min(1000,s.timestamp-previousReplay));previousReplay=s.timestamp;
            thermal.frame(s.raw,s.timestamp);List<Integer> pins=thermal.points();double[] values=new double[pins.size()];for(int n=0;n<values.length;n++)values[n]=thermal.sample(pins.get(n));graph.add(s.timestamp,values);
            stats.setText("Recording · "+new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS",Locale.US).format(new Date(s.timestamp)));status.setText("RAW playback — palette, scale, rotation and mirror remain adjustable");
            int generation=replayGeneration.current();ui.postDelayed(()->{if(replayGeneration.isCurrent(generation))nextReplay();},delay);
        }catch(IOException e){playing=false;status.setText("Recording error: "+e.getMessage());}}
    protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);
        if(result!=RESULT_OK||data==null||data.getData()==null)return;Uri uri=data.getData();
        if(request==IMPORT_RAW){try{openReplay(getContentResolver().openInputStream(uri));}catch(Exception e){status("Cannot open recording: "+e.getMessage());}return;}
        final Bitmap image=pendingSnapshot;final File file=exportFile;
        new Thread(()->{try(OutputStream out=getContentResolver().openOutputStream(uri)){
            if(out==null)throw new IOException("Cannot open destination");
            if(request==SAVE_PNG&&image!=null){if(!image.compress(Bitmap.CompressFormat.PNG,100,out))throw new IOException("PNG save failed");}
            else if(request==EXPORT_RAW&&file!=null)try(InputStream in=new FileInputStream(file)){byte[] b=new byte[65536];int n;while((n=in.read(b))>=0)out.write(b,0,n);}
            status("Saved successfully");
        }catch(Exception e){status("Save failed: "+e.getMessage());}},"FLIR export").start();}
    private EditText number(LinearLayout box,String label,double value){TextView t=new TextView(this);t.setText(label);box.addView(t);
        EditText e=new EditText(this);e.setSingleLine();e.setInputType(8194|4096);e.setText(Double.toString(value));box.addView(e);return e;}
    private Spinner choice(LinearLayout box,String label,String[] values,String selected){TextView t=new TextView(this);t.setText(label);box.addView(t);
        Spinner s=new Spinner(this);s.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,values));box.addView(s);
        for(int i=0;i<values.length;i++)if(values[i].equals(selected))s.setSelection(i);return s;}
    private void settings(){Thermal.Settings s=thermal.settings;LinearLayout box=new LinearLayout(this);box.setOrientation(1);box.setPadding(dp(16),dp(8),dp(16),dp(8));
        Spinner palette=choice(box,"Palette",new String[]{"Iron","White hot","Black hot","Rainbow"},s.palette);
        Spinner scale=choice(box,"Scale",new String[]{"Auto","Linear auto","Manual"},s.scale);
        EditText low=number(box,"Manual minimum °C",s.low),high=number(box,"Manual maximum °C",s.high),tone=number(box,"Tone (−100…100)",s.tone),span=number(box,"Display span % (25…400)",s.span);
        EditText emissivity=number(box,"Emissivity (0.1…1)",s.emissivity),reflected=number(box,"Reflected temperature °C",s.reflected),offset=number(box,"Calibration offset °C",s.offset);
        TextView note=new TextView(this);note.setText("Display controls never alter stored RAW. Temperature estimates use the Windows calibration model. Visible camera / MSX is not yet supported.");box.addView(note);
        ScrollView scroll=new ScrollView(this);scroll.addView(box);
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("Display & temperature").setView(scroll).setPositiveButton("Apply",null).setNeutralButton("Reset",(d,w)->{Thermal.Settings defaults=new Thermal.Settings();s.palette=defaults.palette;s.scale=defaults.scale;s.low=15;s.high=35;s.tone=0;s.span=100;s.emissivity=.95;s.reflected=20;s.offset=0;thermal.refresh();saveSettings();}).setNegativeButton("Cancel",null).create();
        dialog.setOnShowListener(d->dialog.getButton(-1).setOnClickListener(v->{try{
            double l=finite(low),h=finite(high),e=finite(emissivity),r=finite(reflected),o=finite(offset),t=finite(tone),sp=finite(span);
            if(h<=l||e<.1||e>1||r<=-273.15||t< -100||t>100||sp<25||sp>400)throw new IllegalArgumentException("Check ranges; maximum must exceed minimum");
            s.palette=palette.getSelectedItem().toString();s.scale=scale.getSelectedItem().toString();s.low=l;s.high=h;s.emissivity=e;s.reflected=r;s.offset=o;s.tone=t;s.span=sp;
            thermal.refresh();saveSettings();dialog.dismiss();
        }catch(Exception ex){Toast.makeText(this,"Invalid setting: "+ex.getMessage(),Toast.LENGTH_LONG).show();}}));dialog.show();}
    private double finite(EditText e){double v=Double.parseDouble(e.getText().toString());if(!Double.isFinite(v))throw new IllegalArgumentException("Finite number required");return v;}
    private void saveSettings(){Thermal.Settings s=thermal.settings;getPreferences(0).edit().putString("palette",s.palette).putString("scale",s.scale)
        .putFloat("low",(float)s.low).putFloat("high",(float)s.high).putFloat("tone",(float)s.tone).putFloat("span",(float)s.span)
        .putFloat("emissivity",(float)s.emissivity).putFloat("reflected",(float)s.reflected).putFloat("offset",(float)s.offset).putInt("rotation",s.rotation).putBoolean("mirror",s.mirror).apply();}
    private void loadSettings(){android.content.SharedPreferences p=getPreferences(0);Thermal.Settings s=thermal.settings;
        s.palette=p.getString("palette","Iron");s.scale=p.getString("scale","Auto");s.low=p.getFloat("low",15);s.high=p.getFloat("high",35);s.tone=p.getFloat("tone",0);s.span=p.getFloat("span",100);
        s.emissivity=p.getFloat("emissivity",.95f);s.reflected=p.getFloat("reflected",20);s.offset=p.getFloat("offset",0);s.rotation=p.getInt("rotation",0);s.mirror=p.getBoolean("mirror",false);}
}
