package com.dsefa.flir;

import android.app.*;
import android.content.*;
import android.hardware.usb.*;
import android.os.*;
import android.graphics.Bitmap;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import java.text.SimpleDateFormat;

public final class MainActivity extends Activity implements UsbCamera.Listener {
    private static final String USB_PERMISSION="com.dsefa.flir.USB_PERMISSION";
    private static final int SAVE_PNG=20,IMPORT_RAW=21,EXPORT_RAW=22,EXPORT_CSV=23;
    private UsbManager usb;private UsbCamera camera;private TextView status,stats;
    private ThermalView thermal;private GraphView graph;private final Handler ui=new Handler(Looper.getMainLooper());
    private final AtomicReference<RawArchive.Sample> latest=new AtomicReference<>();
    private final AtomicReference<FramePipeline.Result> rendered=new AtomicReference<>();
    private volatile ImageRecorder recorder;private File recordingFile,exportFile;
    private ImageEncoder imageEncoder;
    private final Map<File,ImageRecorder> archiveWriters=new HashMap<>();
    private FramePipeline pipeline;private volatile long lastImageRecord;private final Object fpsLock=new Object();private final Deque<Long> receivedTimes=new ArrayDeque<>();
    private Thermal.Settings exportSettings;private int[] exportPoints=new int[0];private boolean exportCsv;
    private final Generation cameraGeneration=new Generation(),replayGeneration=new Generation(),loadGeneration=new Generation();
    private Bitmap pendingSnapshot;private Button recordButton,freezeButton,playButton;
    private boolean active,frozen,replaying,playing,graphPaused;
    private RecordingIndex replayIndex;private ImageClip.Reader clipReader;private File replayFile;private boolean replayPinned;
    private int replayPosition;private long displayedReplayStamp;private double replaySpeed=1;private boolean seeking;
    private SeekBar replaySeek;private TextView replayLabel;private LinearLayout replayChrome,topChrome;
    private final ChromeState chrome=new ChromeState();private boolean revealGesture;
    private final Deque<Long> times=new ArrayDeque<>();private long lastReceived;
    private String connectionMessage="Turn on the camera and connect its USB data cable through OTG";
    private final UsbPermissionGate permissionGate=new UsbPermissionGate();
    private Dialog controlsDialog;private StorageBudget storage;
    private long storageMb=1000;private volatile String lastRecordingError;
    private final BroadcastReceiver receiver=new BroadcastReceiver(){public void onReceive(Context context,Intent intent){
        if(USB_PERMISSION.equals(intent.getAction())){
            UsbDevice device=intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
            boolean granted=intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED,false);
            if(device==null||!permissionGate.finish(device.getDeviceName(),granted))return;
            if(granted)connect();else status("USB access denied · Settings → Connect to retry");}
        else if(UsbManager.ACTION_USB_DEVICE_DETACHED.equals(intent.getAction())){
            UsbDevice d=intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
            if(d!=null&&d.getVendorId()==0x09CB&&d.getProductId()==0x1996){permissionGate.detached(d.getDeviceName());stopCamera();status("Camera disconnected — reconnect USB");}}
        else if(UsbManager.ACTION_USB_DEVICE_ATTACHED.equals(intent.getAction()))ui.postDelayed(()->{if(active)connect();},250);
    }};
    protected void onCreate(Bundle state){super.onCreate(state);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        usb=(UsbManager)getSystemService(USB_SERVICE);buildUi();imageEncoder=new ImageEncoder(this::status);
        if(state!=null&&state.getString("pendingExport")!=null&&storage!=null){try{
            exportFile=new File(state.getString("pendingExport"));storage.restorePin(exportFile);exportCsv=state.getBoolean("exportCsv");exportSettings=thermal.settings.copy();int[] saved=state.getIntArray("exportPoints");if(saved!=null)exportPoints=saved;
        }catch(IOException e){exportFile=null;status("Pending export unavailable; select the recording again");}}
        IntentFilter filter=new IntentFilter(USB_PERMISSION);filter.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);filter.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
        if(Build.VERSION.SDK_INT>=33)registerReceiver(receiver,filter,Context.RECEIVER_NOT_EXPORTED);else registerReceiver(receiver,filter);
    }
    protected void onStart(){super.onStart();active=true;ui.postDelayed(()->{if(active)connect();},250);ui.post(refresh);showChrome();}
    protected void onStop(){active=false;loadGeneration.advance();ui.removeCallbacks(refresh);ui.removeCallbacks(hideChrome);stopCamera();stopRecording();playing=false;replayGeneration.advance();super.onStop();}
    protected void onSaveInstanceState(Bundle state){if(exportFile!=null){state.putString("pendingExport",exportFile.getAbsolutePath());state.putBoolean("exportCsv",exportCsv);state.putIntArray("exportPoints",exportPoints);}super.onSaveInstanceState(state);}
    protected void onDestroy(){unregisterReceiver(receiver);closeReplay();if(pipeline!=null)pipeline.close();if(imageEncoder!=null)imageEncoder.close();if(controlsDialog!=null)controlsDialog.dismiss();if(!isChangingConfigurations()&&exportFile!=null&&storage!=null)storage.unpin(exportFile);super.onDestroy();}
    protected void onNewIntent(Intent i){super.onNewIntent(i);setIntent(i);if(active)connect();}
    private int dp(int n){return (int)(n*getResources().getDisplayMetrics().density+.5f);}
    private final Runnable hideChrome=()->{if(active&&chrome.hidden(SystemClock.uptimeMillis())&&(controlsDialog==null||!controlsDialog.isShowing())){topChrome.setVisibility(View.GONE);}};
    private void showChrome(){if(topChrome==null)return;chrome.touch(SystemClock.uptimeMillis());topChrome.setVisibility(View.VISIBLE);ui.removeCallbacks(hideChrome);ui.postDelayed(hideChrome,4000);}
    public boolean dispatchTouchEvent(MotionEvent e){if(e.getActionMasked()==MotionEvent.ACTION_DOWN){revealGesture=topChrome!=null&&topChrome.getVisibility()!=View.VISIBLE;showChrome();}else if(e.getActionMasked()==MotionEvent.ACTION_MOVE)showChrome();if(revealGesture){if(e.getActionMasked()==MotionEvent.ACTION_UP||e.getActionMasked()==MotionEvent.ACTION_CANCEL)revealGesture=false;return true;}return super.dispatchTouchEvent(e);}
    private LinearLayout row(LinearLayout parent){LinearLayout r=new LinearLayout(this);r.setOrientation(LinearLayout.HORIZONTAL);parent.addView(r);return r;}
    private Button button(LinearLayout parent,String label,Runnable action){Button b=new Button(this);b.setText(label);b.setTextSize(12);b.setAllCaps(false);b.setPadding(dp(6),0,dp(6),0);b.setMinWidth(0);b.setMinHeight(dp(44));b.setTextColor(0xffeff5ff);
        b.setBackground(new android.graphics.drawable.RippleDrawable(android.content.res.ColorStateList.valueOf(0x447fded2),surface(0xff1c2a39,12),null));
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,dp(48),1);p.setMargins(dp(3),dp(3),dp(3),dp(3));parent.addView(b,p);b.setOnClickListener(v->action.run());return b;}
    private GradientDrawable surface(int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;}
    private void section(LinearLayout parent,String text){TextView t=new TextView(this);t.setText(text);t.setTextColor(0xff7fded2);t.setTextSize(11);t.setLetterSpacing(.12f);t.setPadding(dp(8),dp(22),dp(8),dp(8));parent.addView(t);}
    private void resetMeasurements(){thermal.resetMeasurements();graph.clear();graphPaused=false;graph.pause(false);Toast.makeText(this,"Measurements and graph history reset",Toast.LENGTH_SHORT).show();}
    private void showControls(){controlsDialog.show();Window w=controlsDialog.getWindow();if(w!=null){w.setBackgroundDrawable(surface(0xff111923,24));w.setGravity(Gravity.BOTTOM);w.setLayout(-1,(int)(getResources().getDisplayMetrics().heightPixels*.76));}}
    private void buildUi(){
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN|View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY|View.SYSTEM_UI_FLAG_LAYOUT_STABLE|View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN|View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        FrameLayout full=new FrameLayout(this);full.setBackgroundColor(0xff050609);setContentView(full);
        thermal=new ThermalView(this);full.addView(thermal,new FrameLayout.LayoutParams(-1,-1));
        LinearLayout top=new LinearLayout(this);topChrome=top;top.setOrientation(1);top.setPadding(dp(12),dp(8),dp(12),dp(8));
        FrameLayout.LayoutParams topLayout=new FrameLayout.LayoutParams(-1,-2,Gravity.TOP);full.addView(top,topLayout);
        top.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,new int[]{0xc9000000,0x00000000}));
        LinearLayout toolbar=row(top);
        TextView title=new TextView(this);title.setText("FLIR\nGEN 2");title.setTextSize(11);title.setTextColor(0xffeff5ff);title.setGravity(Gravity.CENTER_VERTICAL);title.setLetterSpacing(.1f);
        toolbar.addView(title,new LinearLayout.LayoutParams(0,dp(44),1));
        recordButton=button(toolbar,"● Record",this::toggleRecording);
        Button reset=button(toolbar,"Reset",this::resetMeasurements);reset.setContentDescription("Reset measurements and all graph history; keep recordings");
        Button menu=button(toolbar,"Settings",this::showControls);
        for(Button b:new Button[]{recordButton,reset,menu}){b.setTextColor(0xffeff5ff);b.setAllCaps(false);b.setBackground(surface(0xcc15202c,14));LinearLayout.LayoutParams p=(LinearLayout.LayoutParams)b.getLayoutParams();p.weight=0;p.width=dp(74);p.setMargins(dp(4),0,0,0);b.setLayoutParams(p);}
        status=new TextView(this);status.setTextColor(0xff98adb9);status.setTextSize(10);status.setMaxLines(1);status.setEllipsize(android.text.TextUtils.TruncateAt.END);top.addView(status);
        replayChrome=new LinearLayout(this);replayChrome.setOrientation(1);replayChrome.setVisibility(View.GONE);top.addView(replayChrome);replayLabel=new TextView(this);replayLabel.setTextSize(11);replayLabel.setTextColor(0xffd8e8ef);replayChrome.addView(replayLabel);
        replaySeek=new SeekBar(this);replayChrome.addView(replaySeek);replaySeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){public void onStartTrackingTouch(SeekBar b){seeking=true;playing=false;replayGeneration.advance();}public void onStopTrackingTouch(SeekBar b){seeking=false;seekReplay(b.getProgress());}public void onProgressChanged(SeekBar b,int progress,boolean user){if(user)seekReplay(progress);}});
        LinearLayout timeline=row(replayChrome);button(timeline,"‹",()->stepReplay(-1));button(timeline,"▶ / Ⅱ",this::togglePlayback);button(timeline,"›",()->stepReplay(1));button(timeline,"PNG",this::savePng);button(timeline,"Live",this::returnLive);
        full.setOnApplyWindowInsetsListener((v,insets)->{top.setPadding(dp(12)+insets.getSystemWindowInsetLeft(),dp(8)+insets.getSystemWindowInsetTop(),dp(12)+insets.getSystemWindowInsetRight(),dp(8));thermal.safeBottom(insets.getSystemWindowInsetBottom());return insets;});
        LinearLayout root=new LinearLayout(this);root.setOrientation(1);root.setPadding(dp(14),dp(10),dp(14),dp(24));
        LinearLayout heading=row(root);TextView panelTitle=new TextView(this);panelTitle.setText("Camera controls");panelTitle.setTextColor(0xffeff5ff);panelTitle.setTextSize(20);heading.addView(panelTitle,new LinearLayout.LayoutParams(0,dp(44),2));button(heading,"Close",()->controlsDialog.dismiss());
        stats=new TextView(this);stats.setTextColor(0xff8ba1b5);stats.setTextSize(11);stats.setPadding(dp(8),dp(8),dp(8),dp(8));root.addView(stats);
        section(root,"VIEW");LinearLayout controls=row(root);button(controls,"Rotate 90°",()->{thermal.settings.rotation=(thermal.settings.rotation+90)%360;thermal.refresh();saveSettings();});
        button(controls,"Mirror",()->{thermal.settings.mirror=!thermal.settings.mirror;thermal.refresh();saveSettings();});
        button(controls,"Display",this::settings);
        LinearLayout tracking=row(root);button(tracking,"Track MAX",()->{thermal.trackMaximum=!thermal.trackMaximum;thermal.invalidate();});button(tracking,"Track MIN",()->{thermal.trackMinimum=!thermal.trackMinimum;thermal.invalidate();});button(tracking,"Reset zoom",thermal::resetZoom);
        Switch maxGraph=new Switch(this);maxGraph.setText("Maximum temperature line");maxGraph.setTextSize(13);maxGraph.setPadding(dp(8),dp(12),dp(8),dp(12));maxGraph.setChecked(getPreferences(0).getBoolean("maxGraph",true));thermal.showMaximumGraph=maxGraph.isChecked();root.addView(maxGraph);
        maxGraph.setOnCheckedChangeListener((b,value)->{thermal.showMaximumGraph=value;thermal.invalidate();getPreferences(0).edit().putBoolean("maxGraph",value).apply();});
        section(root,"CAPTURE");
        LinearLayout capture=row(root);freezeButton=button(capture,"Freeze image",()->{frozen=!frozen;freezeButton.setText(frozen?"Resume image":"Freeze image");});
        button(capture,"Save PNG",this::savePng);LinearLayout recording=row(root);button(recording,"Recordings",this::recordings);button(recording,"Live",this::returnLive);
        section(root,"MEASUREMENT HISTORY");graph=new GraphView(this);graph.settings=thermal.settings;root.addView(graph,new LinearLayout.LayoutParams(-1,dp(210)));
        LinearLayout graphButtons=row(root);button(graphButtons,"Pause / Live",()->{graphPaused=!graph.paused();graph.pause(graphPaused);});
        button(graphButtons,"− Zoom",()->graph.zoom(2));button(graphButtons,"+ Zoom",()->graph.zoom(.5));
        LinearLayout resetRow=row(root);button(resetRow,"Reset measurements",this::resetMeasurements);
        section(root,"RECORDINGS & STORAGE");LinearLayout replay=row(root);playButton=button(replay,"Play / Pause",this::togglePlayback);
        button(replay,"Import",()->{Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("application/octet-stream").addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,IMPORT_RAW);});
        button(replay,"Speed",()->new AlertDialog.Builder(this).setTitle("Playback speed").setItems(new String[]{"0.25×","0.5×","1×","2×","4×"},(d,n)->{replaySpeed=new double[]{.25,.5,1,2,4}[n];}).show());
        storageMb=getPreferences(0).getLong("storageMb",1000);
        try{storage=StorageBudget.shared(archiveDir(),StorageBudget.limitFromMb(storageMb));}catch(IOException e){status("Storage unavailable: "+e.getMessage());}
        LinearLayout storageRow=row(root);button(storageRow,"Storage limit",this::storageSettings);
        section(root,"CONNECTION");LinearLayout connection=row(root);button(connection,"Connect",()->{permissionGate.retry();stopCamera();connect();});button(connection,"USB permission",this::usbHelp);
        TextView note=new TextView(this);note.setText("Tap to pin a temperature; tap near a pin to remove it. Pinch the image to zoom. Controls hide after 4 seconds; tap once to reveal.\n\nRecord is manual: 1 JPEG frame / second, no new RAW storage. Saved colours cannot be reprocessed. Older RAW imports remain supported.\nThermal only · visible / MSX unavailable.");note.setTextColor(0xff8ba1b5);note.setTextSize(11);note.setPadding(dp(8),dp(16),dp(8),dp(8));root.addView(note);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.addView(root);controlsDialog=new Dialog(this);controlsDialog.setContentView(scroll);controlsDialog.setOnDismissListener(d->showChrome());
        thermal.listener=p->graph.clear();loadSettings();
    }
    private void connect(){if(!active||replaying||camera!=null)return;
        if(!getPackageManager().hasSystemFeature("android.hardware.usb.host")){status("This phone does not support USB host / OTG");return;}
        UsbDevice found=null;for(UsbDevice d:usb.getDeviceList().values())if(d.getVendorId()==0x09CB&&d.getProductId()==0x1996){found=d;break;}
        if(found==null){status("Camera not found — turn it on and connect USB OTG");return;}
        if(!usb.hasPermission(found)){if(permissionGate.request(found.getDeviceName(),false)){
            PendingIntent pi=PendingIntent.getBroadcast(this,0,new Intent(USB_PERMISSION).setPackage(getPackageName()),PendingIntent.FLAG_MUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
            usb.requestPermission(found,pi);status("Accept Android's USB access permission");}return;}
        final int generation=cameraGeneration.current();
        pipeline=new FramePipeline(result->{
            cameraGeneration.runIfCurrent(generation,()->{ImageRecorder writer=recorder;if(writer!=null&&result.colors!=null&&(lastImageRecord==0||result.timestamp-lastImageRecord>=1000)){
                lastImageRecord=result.timestamp;imageEncoder.submit(writer,result.colors,result.timestamp);}rendered.set(result);});
        },message->ui.post(()->{if(active&&cameraGeneration.isCurrent(generation))status(message);}));
        camera=new UsbCamera(usb,found,new UsbCamera.Listener(){
            public void status(String message){ui.post(()->cameraGeneration.runIfCurrent(generation,()->{
                if(active){connectionMessage=message;status.setText(message);}}));}
            public void frame(int[] r,long t,byte[] jpg,byte[] meta){cameraGeneration.runIfCurrent(generation,()->{
                if(active)MainActivity.this.frame(r,t,jpg,meta);});}
        });camera.start();
    }
    private void stopCamera(){cameraGeneration.advance();if(camera!=null){camera.close();camera=null;}if(pipeline!=null){pipeline.close();pipeline=null;}latest.set(null);rendered.set(null);times.clear();synchronized(fpsLock){receivedTimes.clear();}lastReceived=0;lastPresented=0;}
    public void status(String s){ui.post(()->{if(active){connectionMessage=s;status.setText(s);}});}
    public void frame(int[] raw,long timestamp,byte[] jpeg,byte[] metadata){RawArchive.Sample s=new RawArchive.Sample();s.raw=raw;s.timestamp=timestamp;
        latest.set(s);long now=SystemClock.elapsedRealtime();synchronized(fpsLock){receivedTimes.addLast(now);while(!receivedTimes.isEmpty()&&receivedTimes.getFirst()<now-2000)receivedTimes.removeFirst();}}
    private long lastPresented;
    private double cameraFps(){synchronized(fpsLock){return receivedTimes.size()>1?(receivedTimes.size()-1)*1000./Math.max(1,receivedTimes.getLast()-receivedTimes.getFirst()):0;}}
    private void present(FramePipeline.Result r){lastPresented=r.timestamp;if(!frozen)thermal.result(r);thermal.measure(r.temperatures,r.timestamp);
        addGraph(r.timestamp,r.temperatures);stats.setText(String.format(Locale.US,"%.1f input FPS · 160 × 120 · %s\n%s",cameraFps(),new SimpleDateFormat("HH:mm:ss",Locale.US).format(new Date(r.timestamp)),r.description));
        status.setText(String.format(Locale.US,"%.1f FPS%s%s",cameraFps(),frozen?" · image frozen":"",recorder!=null?" · REC 1 fps":""));}
    private void addGraph(long stamp,double[] values){List<Integer> pins=thermal.points();double[] v=new double[pins.size()+1];v[0]=Double.NaN;for(double t:values)if(Double.isFinite(t)&&(Double.isNaN(v[0])||t>v[0]))v[0]=t;
        for(int i=0;i<pins.size();i++)v[i+1]=Thermal.sample(values,pins.get(i),thermal.settings.average);graph.add(stamp,v);}
    private final Runnable refresh=new Runnable(){public void run(){if(!active)return;
        FramePipeline.Result processed=rendered.getAndSet(null);if(processed!=null&&!replaying&&processed.timestamp>=lastPresented)present(processed);
        RawArchive.Sample s=latest.getAndSet(null);if(s!=null&&!replaying){lastReceived=System.currentTimeMillis();times.addLast(lastReceived);
            while(!times.isEmpty()&&times.getFirst()<lastReceived-2000)times.removeFirst();
            if(pipeline!=null)pipeline.submit(s.raw,s.timestamp,thermal.settings,!frozen||recorder!=null);
        }else if(!replaying&&lastReceived>0&&System.currentTimeMillis()-lastReceived>2500){status.setText("No fresh frame for "+(System.currentTimeMillis()-lastReceived)/1000+"s · "+connectionMessage);}
        if(recorder!=null&&recorder.complete()){stopRecording();Toast.makeText(MainActivity.this,lastRecordingError==null?"Recording stopped":lastRecordingError,Toast.LENGTH_LONG).show();}
        archiveWriters.entrySet().removeIf(entry->entry.getValue().complete());
        ui.postDelayed(this,8);
    }};
    private void savePng(){if(thermal.timestamp()==0){status("No frame to save");return;}pendingSnapshot=thermal.snapshot();
        Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("image/png").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE,"FLIR-"+dateName()+".png");startActivityForResult(i,SAVE_PNG);}
    private String dateName(){return new SimpleDateFormat("yyyy-MM-dd_HH-mm-ss",Locale.US).format(new Date());}
    private File archiveDir(){File f=new File(getFilesDir(),"recordings");f.mkdirs();return f;}
    private void toggleRecording(){loadGeneration.advance();if(recorder!=null){stopRecording();return;}if(replaying){status("Return to Live before recording");return;}
        if(thermal.raw()==null){status("Wait for a live camera frame before recording");return;}
        recordingFile=new File(archiveDir(),"FLIR-"+dateName()+"-"+UUID.randomUUID().toString().substring(0,8)+".f1clip");
        try{if(storage==null)throw new IOException("Recording storage unavailable");lastRecordingError=null;
            lastImageRecord=0;recorder=new ImageRecorder(recordingFile,s->{lastRecordingError=s;status(s);},storage,16000000);archiveWriters.put(recordingFile,recorder);recordButton.setText("■ Stop");recordButton.setTextColor(0xffff8e91);}
        catch(IOException e){status("Cannot record: "+e.getMessage());}}
    private void stopRecording(){ImageRecorder r=recorder;recorder=null;if(r!=null)r.close();if(recordButton!=null){recordButton.setText("● Record");recordButton.setTextColor(0xffeff5ff);}}
    private void recordings(){browseRecordings(null);}
    private void browseRecordings(String selectedDate){
        new Thread(()->{List<File> files=new ArrayList<>();List<String> labels=new ArrayList<>();Set<String> days=new TreeSet<>(Collections.reverseOrder());
            File[] all=archiveDir().listFiles((dir,name)->name.endsWith(".f1raw")||name.endsWith(".f1clip"));if(all!=null)Arrays.sort(all,Comparator.comparing(File::getName).reversed());
            if(all!=null)for(File f:all){if(storage!=null&&storage.isActive(f))continue;boolean held=false;try{if(storage!=null){storage.pin(f);held=true;}
                long first,last;int count;if(f.getName().endsWith(".f1clip")){try(ImageClip.Reader r=new ImageClip.Reader(f)){first=r.firstTimestamp();last=r.lastTimestamp();count=r.count();}}
                else{try(RecordingIndex r=new RecordingIndex(f)){first=r.firstTimestamp();last=r.lastTimestamp();count=r.count();}}
                String day=new SimpleDateFormat("yyyy-MM-dd",Locale.US).format(new Date(first));days.add(day);if(selectedDate!=null&&!day.equals(selectedDate))continue;
                files.add(f);labels.add(new SimpleDateFormat("MMM d · HH:mm:ss",Locale.US).format(new Date(first))+String.format(Locale.US,"  ·  %ds  ·  %.1f MB\n%s · %d frames",(last-first)/1000,f.length()/1000000.,f.getName().endsWith(".f1clip")?"Image clip":"RAW",count));
            }catch(IOException ignored){}finally{if(held)storage.unpin(f);}}
            ui.post(()->{if(!active||isFinishing())return;if(files.isEmpty()&&selectedDate==null){new AlertDialog.Builder(this).setTitle("Recordings").setMessage("No completed recordings yet. Tap ● Record to save one image per second. Stop recording before browsing the current segment.").setPositiveButton("OK",null).show();return;}
                new AlertDialog.Builder(this).setTitle(selectedDate==null?"Recordings · newest first":selectedDate).setItems(labels.toArray(new String[0]),(d,n)->recordingActions(files.get(n)))
                    .setNeutralButton("Choose date",(d,w)->{String[] dates=days.toArray(new String[0]);new AlertDialog.Builder(this).setTitle("Capture date").setItems(dates,(dd,n)->browseRecordings(dates[n])).setNeutralButton("Calendar",(dd,w2)->{Calendar cal=Calendar.getInstance();new DatePickerDialog(this,(view,y,m,day)->browseRecordings(String.format(Locale.US,"%04d-%02d-%02d",y,m+1,day)),cal.get(Calendar.YEAR),cal.get(Calendar.MONTH),cal.get(Calendar.DAY_OF_MONTH)).show();}).setNegativeButton("All",(dd,w2)->browseRecordings(null)).show();}).setNegativeButton("Close",null).show();});
        },"recording catalog").start();}
    private void recordingActions(File f){boolean raw=f.getName().endsWith(".f1raw");new AlertDialog.Builder(this).setTitle(f.getName()).setItems(raw?new String[]{"Play / analyse RAW","Export RAW","Export temperatures CSV"}:new String[]{"Play image clip","Export image clip"},(d,n)->{
        if(n==0){try{openReplay(f);}catch(IOException e){status("Cannot play: "+e.getMessage());}}
        else startExport(f,n==2);
    }).show();}
    private void startExport(File f,boolean csv){try{if(storage==null)throw new IOException("Recording storage unavailable");storage.pin(f);exportFile=f;exportCsv=csv;exportSettings=thermal.settings.copy();exportPoints=thermal.points().stream().mapToInt(Integer::intValue).toArray();
        Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT).setType(csv?"text/csv":"application/octet-stream").putExtra(Intent.EXTRA_TITLE,csv?f.getName()+".csv":f.getName()).addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,csv?EXPORT_CSV:EXPORT_RAW);
    }catch(Exception e){if(exportFile!=null&&storage!=null)storage.unpin(exportFile);exportFile=null;status("Cannot export: "+e.getMessage());}}
    private void closeReplay(){replayGeneration.advance();playing=false;try{if(replayIndex!=null)replayIndex.close();if(clipReader!=null)clipReader.close();}catch(IOException ignored){}replayIndex=null;clipReader=null;
        if(replayPinned&&storage!=null&&replayFile!=null)storage.unpin(replayFile);if(replayFile!=null&&replayFile.getParentFile().equals(getCacheDir()))replayFile.delete();replayPinned=false;replayFile=null;}
    private void returnLive(){loadGeneration.advance();closeReplay();replaying=false;playing=false;frozen=false;freezeButton.setText("Freeze image");thermal.resetTimeline();graph.clear();replayChrome.setVisibility(View.GONE);connect();}
    private void openReplay(File f)throws IOException{final int token=loadGeneration.advance();status("Opening recording…");new Thread(()->{
        RecordingIndex raw=null;ImageClip.Reader clip=null;boolean pinned=false;try{
            if(!loadGeneration.isCurrent(token)){disposeLoaded(f,null,null,false);return;}
            if(storage!=null&&f.getCanonicalFile().getParentFile().equals(archiveDir().getCanonicalFile())){storage.pin(f);pinned=true;}
            if(f.getName().endsWith(".f1clip"))clip=new ImageClip.Reader(f);else raw=new RecordingIndex(f);
            final RecordingIndex readyRaw=raw;final ImageClip.Reader readyClip=clip;final boolean held=pinned;
            ui.post(()->{if(!active||!loadGeneration.isCurrent(token)){disposeLoaded(f,readyRaw,readyClip,held);return;}
                stopRecording();stopCamera();closeReplay();replayFile=f;replayPinned=held;replayIndex=readyRaw;clipReader=readyClip;replaying=true;playing=false;replayPosition=0;graph.clear();thermal.resetTimeline();
                replaySeek.setMax(replayCount()-1);replayChrome.setVisibility(View.VISIBLE);showChrome();controlsDialog.dismiss();
                try{showReplay(0);playing=true;scheduleReplay();}catch(IOException e){status("Cannot play: "+e.getMessage());closeReplay();replaying=false;connect();}
            });
        }catch(Exception e){disposeLoaded(f,raw,clip,pinned);if(loadGeneration.isCurrent(token))status("Cannot open recording: "+e.getMessage());}
    },"recording loader").start();}
    private void disposeLoaded(File f,RecordingIndex raw,ImageClip.Reader clip,boolean pinned){try{if(raw!=null)raw.close();if(clip!=null)clip.close();}catch(IOException ignored){}if(pinned&&storage!=null)storage.unpin(f);if(f.getParentFile().equals(getCacheDir()))f.delete();}
    private int replayCount(){return clipReader!=null?clipReader.count():replayIndex!=null?replayIndex.count():0;}
    private long replayStamp(int n)throws IOException{return clipReader!=null?clipReader.timestamp(n):replayIndex.timestamp(n);}
    private void showReplay(int n)throws IOException{replayPosition=n;long stamp;
        if(clipReader!=null){ImageClip.Sample sample=clipReader.read(n);stamp=sample.timestamp;try{thermal.savedImage(sample.jpeg,stamp);}catch(IllegalArgumentException e){throw new IOException(e.getMessage(),e);}}
        else{RawArchive.Sample sample=replayIndex.read(n);stamp=sample.timestamp;thermal.frame(sample.raw,stamp);thermal.measure(thermal.temperatures(),stamp);addGraph(stamp,thermal.temperatures());}
        displayedReplayStamp=stamp;replaySeek.setProgress(n);String date=new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.US).format(new Date(stamp));replayLabel.setText(date+"   ·   "+(n+1)+" / "+replayCount()+"   ·   "+replaySpeed+"×");
        status.setText(clipReader!=null?"Image playback · saved colours · rotate / mirror available":"RAW playback · full display / temperature controls");stats.setText("Recording · "+date);}
    private void seekReplay(int n){if(!replaying||replayCount()==0)return;replayGeneration.advance();playing=false;graph.clear();thermal.resetTimeline();try{showReplay(Math.max(0,Math.min(replayCount()-1,n)));}catch(IOException e){status(e.getMessage());}}
    private void stepReplay(int delta){seekReplay(replayPosition+delta);}
    private void togglePlayback(){if(!replaying)return;replayGeneration.advance();playing=!playing;if(playing){if(replayPosition>=replayCount()-1){seekReplay(0);playing=true;}scheduleReplay();}}
    private void scheduleReplay(){if(!active||!replaying||!playing||seeking)return;if(replayPosition>=replayCount()-1){playing=false;return;}try{
        long delay=(long)Math.max(1,Math.min(60000,(replayStamp(replayPosition+1)-displayedReplayStamp)/replaySpeed));int generation=replayGeneration.current();ui.postDelayed(()->{if(!active||!playing||!replayGeneration.isCurrent(generation))return;try{showReplay(replayPosition+1);scheduleReplay();}catch(IOException e){playing=false;status(e.getMessage());}},delay);
    }catch(IOException e){playing=false;status(e.getMessage());}}
    protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);
        if(result!=RESULT_OK||data==null||data.getData()==null){if((request==EXPORT_RAW||request==EXPORT_CSV)&&exportFile!=null&&storage!=null){storage.unpin(exportFile);exportFile=null;}return;}Uri uri=data.getData();
        if(request==IMPORT_RAW){importRecording(uri);return;}
        final Bitmap image=pendingSnapshot;final File file=exportFile;final StorageBudget exportBudget=storage;final Thermal.Settings csvSettings=exportSettings==null?thermal.settings.copy():exportSettings;final int[] csvPoints=exportPoints.clone();if(request==EXPORT_RAW||request==EXPORT_CSV)exportFile=null;
        if((request==EXPORT_RAW||request==EXPORT_CSV)&&(file==null||!file.isFile())){if(file!=null&&exportBudget!=null)exportBudget.unpin(file);status("Export source unavailable — select the recording again");return;}
        if(request==SAVE_PNG&&image==null){status("Snapshot unavailable — tap Save PNG again");return;}
        new Thread(()->{try(OutputStream out=getContentResolver().openOutputStream(uri)){
            if(out==null)throw new IOException("Cannot open destination");
            if(request==SAVE_PNG&&image!=null){if(!image.compress(Bitmap.CompressFormat.PNG,100,out))throw new IOException("PNG save failed");}
            else if(request==EXPORT_RAW&&file!=null)try(InputStream in=new FileInputStream(file)){byte[] b=new byte[65536];int n;while((n=in.read(b))>=0)out.write(b,0,n);}
            else if(request==EXPORT_CSV)CsvExport.write(file,out,csvSettings,csvPoints);
            status("Saved successfully");
        }catch(Exception e){status("Save failed: "+e.getMessage());}finally{if((request==EXPORT_RAW||request==EXPORT_CSV)&&file!=null&&exportBudget!=null)exportBudget.unpin(file);}},"FLIR export").start();}
    private void importRecording(Uri uri){final int token=loadGeneration.advance();status("Importing recording…");new Thread(()->{File temp=new File(getCacheDir(),"import-"+UUID.randomUUID()+".f1raw");try{
        try(InputStream in=getContentResolver().openInputStream(uri);OutputStream out=new FileOutputStream(temp)){if(in==null)throw new IOException("Cannot open selected file");byte[] bytes=new byte[65536];int n;long size=0;while((n=in.read(bytes))!=-1){if(!loadGeneration.isCurrent(token))throw new IOException("Import cancelled");size+=n;if(size>StorageBudget.limitFromMb(storageMb))throw new IOException("Import exceeds recording storage limit");out.write(bytes,0,n);}}
        try(DataInputStream in=new DataInputStream(new FileInputStream(temp))){if(in.readInt()==0x46314A31){File clip=new File(getCacheDir(),temp.getName()+".f1clip");if(!temp.renameTo(clip))throw new IOException("Cannot prepare imported clip");temp=clip;}}
        final File ready=temp;ui.post(()->{if(!active||!loadGeneration.isCurrent(token)){ready.delete();return;}try{openReplay(ready);}catch(IOException e){ready.delete();status("Cannot open recording: "+e.getMessage());}});
    }catch(Exception e){temp.delete();if(loadGeneration.isCurrent(token))status("Cannot import: "+e.getMessage());}},"recording import").start();}
    private EditText number(LinearLayout box,String label,double value){TextView t=new TextView(this);t.setText(label);box.addView(t);
        EditText e=new EditText(this);e.setSingleLine();e.setInputType(8194|4096);e.setText(Double.toString(value));box.addView(e);return e;}
    private Spinner choice(LinearLayout box,String label,String[] values,String selected){TextView t=new TextView(this);t.setText(label);box.addView(t);
        Spinner s=new Spinner(this);s.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,values));box.addView(s);
        for(int i=0;i<values.length;i++)if(values[i].equals(selected))s.setSelection(i);return s;}
    private void usbHelp(){new AlertDialog.Builder(this).setTitle("USB access").setMessage("When Android offers this app for the camera, select Always / Use by default if available. This is a system preference, not a permission the app can save itself.\n\nAndroid revokes USB access on unplug. Some phones ask again after reconnection or a camera reset. We never bypass this security check.\n\nIf another app is the default, clear its Open by default settings. Then reconnect the camera and select FLIR Gen2 Thermal.").setPositiveButton("OK",null).show();}
    private void storageSettings(){LinearLayout box=new LinearLayout(this);box.setOrientation(1);box.setPadding(dp(20),dp(12),dp(20),dp(12));
        EditText limit=number(box,"Recording storage limit · MB (100–10,000)",storageMb);
        TextView explanation=new TextView(this);explanation.setText("Default: 1,000 MB (1 GB). Maximum: 10 GB.\n\nRecording is manual: 1 image per second. When full, the oldest completed app recordings are automatically deleted. Export anything you want to keep. Active recording, playback and export files are protected.\n\nA lower limit takes effect when you next record.");explanation.setTextSize(12);box.addView(explanation);
        AlertDialog d=new AlertDialog.Builder(this).setTitle("Recording storage").setView(box).setPositiveButton("Apply",null).setNegativeButton("Cancel",null).create();
        d.setOnShowListener(a->d.getButton(-1).setOnClickListener(v->{try{double value=finite(limit);if(value<100||value>10000||value!=Math.floor(value))throw new IllegalArgumentException("Enter a whole number from 100 to 10,000 MB");
            storageMb=(long)value;getPreferences(0).edit().putLong("storageMb",storageMb).apply();if(storage!=null)storage.setLimit(StorageBudget.limitFromMb(storageMb));d.dismiss();
        }catch(Exception e){limit.setError(e.getMessage());}}));d.show();}
    private void settings(){controlsDialog.dismiss();new SettingsPanel(this,thermal.settings,()->{if(replaying||camera==null)thermal.refresh();graph.invalidate();saveSettings();}).show();}
    private double finite(EditText e){double v=Double.parseDouble(e.getText().toString());if(!Double.isFinite(v))throw new IllegalArgumentException("Finite number required");return v;}
    private void saveSettings(){Thermal.Settings s=thermal.settings;getPreferences(0).edit().putString("palette",s.palette).putString("scale",s.scale)
        .putFloat("low",(float)s.low).putFloat("high",(float)s.high).putFloat("tone",(float)s.tone).putFloat("span",(float)s.span)
        .putFloat("emissivity",(float)s.emissivity).putFloat("reflected",(float)s.reflected).putFloat("offset",(float)s.offset).putInt("rotation",s.rotation).putBoolean("mirror",s.mirror)
        .putFloat("contrast",(float)s.contrast).putFloat("minSpan",(float)s.minSpan).putFloat("detail",(float)s.detail).putFloat("denoise",(float)s.denoise).putFloat("deadband",(float)s.deadband).putFloat("hotSpan",(float)s.hotSpan).putFloat("learning",(float)s.learningSeconds)
        .putBoolean("average",s.average).putBoolean("fahrenheit",s.fahrenheit).putBoolean("smooth",s.smooth).apply();}
    private void loadSettings(){android.content.SharedPreferences p=getPreferences(0);Thermal.Settings s=thermal.settings;
        s.palette=p.getString("palette","Iron");s.scale=p.getString("scale","Auto");s.low=p.getFloat("low",15);s.high=p.getFloat("high",35);s.tone=p.getFloat("tone",0);s.span=p.getFloat("span",100);
        s.emissivity=p.getFloat("emissivity",.95f);s.reflected=p.getFloat("reflected",20);s.offset=p.getFloat("offset",0);s.rotation=p.getInt("rotation",0);s.mirror=p.getBoolean("mirror",false);
        s.contrast=p.getFloat("contrast",1.5f);s.minSpan=p.getFloat("minSpan",1.5f);s.detail=p.getFloat("detail",35);s.denoise=p.getFloat("denoise",30);s.deadband=p.getFloat("deadband",.25f);s.hotSpan=p.getFloat("hotSpan",3);s.learningSeconds=p.getFloat("learning",120);
        s.average=p.getBoolean("average",true);s.fahrenheit=p.getBoolean("fahrenheit",false);s.smooth=p.getBoolean("smooth",true);}
}
