package com.dsefa.flir;

import android.hardware.usb.*;
import android.os.SystemClock;
import java.io.*;
import java.util.*;

/** USB lifetime is confined to one worker. No UI or filesystem on the read path. */
public final class UsbCamera implements AutoCloseable {
    public interface Listener {
        void status(String message);
        void frame(int[] raw,long timestamp,byte[] jpeg,byte[] status);
    }
    private final UsbManager manager;private final UsbDevice device;private final Listener listener;
    private volatile boolean running;private volatile UsbDeviceConnection connection;
    private UsbEndpoint input,output,frameInput;private Thread thread;
    private UsbInterface c0,f0,f1,v0,v1;
    public UsbCamera(UsbManager m,UsbDevice d,Listener l){manager=m;device=d;listener=l;}
    public void start(){if(running)return;running=true;thread=new Thread(this::run,"FLIR USB");thread.start();}
    public void close(){running=false;UsbDeviceConnection c=connection;if(c!=null)c.close();if(thread!=null)thread.interrupt();}
    private void message(String s){if(running)listener.status(s);}
    private UsbInterface iface(int id,int alt)throws IOException{
        for(int i=0;i<device.getInterfaceCount();i++){UsbInterface f=device.getInterface(i);if(f.getId()==id&&f.getAlternateSetting()==alt)return f;}
        throw new IOException("Missing USB interface "+id+" alt "+alt);
    }
    private UsbEndpoint endpoint(UsbInterface f,int address)throws IOException{
        for(int i=0;i<f.getEndpointCount();i++){UsbEndpoint e=f.getEndpoint(i);if(e.getAddress()==address){
            if(e.getType()!=UsbConstants.USB_ENDPOINT_XFER_BULK)throw new IOException("Endpoint "+address+" is not bulk");return e;}}
        throw new IOException("Missing endpoint 0x"+Integer.toHexString(address));
    }
    private void alt(UsbInterface f)throws IOException{if(!connection.setInterface(f))throw new IOException("Cannot select MI"+f.getId()+" alt "+f.getAlternateSetting());}
    private void write(byte[] b)throws IOException{
        for(int attempt=0;attempt<4&&running;attempt++){
            int n=connection.bulkTransfer(output,b,b.length,500);
            if(n==b.length)return;
            if(n>=0)throw new IOException("Partial iAP2 USB write: "+n+"/"+b.length);
            SystemClock.sleep(30L*(attempt+1));
        }throw new IOException("iAP2 USB write failed");
    }
    private void startStream()throws IOException{
        alt(v0);alt(f0);alt(f1);alt(v1);
        frameInput=endpoint(v1,0x85);
        // CLEAR_FEATURE(ENDPOINT_HALT), same optional step as Windows.
        connection.controlTransfer(2,1,0,0x85,null,0,200);
        message("iAP2 config session active — waiting for thermal frames");
    }
    private void run(){Generation.serializedUsb(this::runExclusive);}
    private void runExclusive(){
        if(!running)return;
        try{
            c0=iface(0,0);f0=iface(1,0);f1=iface(1,1);v0=iface(2,0);v1=iface(2,1);
        }catch(IOException e){message(e.getMessage());running=false;return;}
        while(running){
            try{
                connection=manager.openDevice(device);if(connection==null)throw new IOException("Cannot open camera (USB permission or cable)");
                if(!connection.claimInterface(c0,true)||!connection.claimInterface(f0,true)||!connection.claimInterface(v0,true))throw new IOException("Cannot claim FLIR USB interfaces");
                input=endpoint(c0,0x81);output=endpoint(c0,0x02);
                Protocol.LinkStream links=new Protocol.LinkStream();FrameParser frames=new FrameParser();
                IapSession session=new IapSession(this::write,this::startStream);
                byte[] cb=new byte[16384],fb=new byte[16384];
                long start=SystemClock.elapsedRealtime(),lastFrame=start,cooldown=0;int restarts=0,skip=0,lastSpan=-1;
                boolean first=true;message("USB connected — establishing iAP2 session");
                while(running){
                    long now=SystemClock.elapsedRealtime();
                    if(session.streaming()){
                        int n=connection.bulkTransfer(frameInput,fb,fb.length,25);
                        if(n>0){frames.add(fb,n);FrameParser.Frame frame;
                            while((frame=frames.pop())!=null){lastFrame=SystemClock.elapsedRealtime();restarts=0;
                                if(first){message("EP85: Frame="+Protocol.le32(frame.record,8)+" Thermal="+frame.thermalSize+" JPEG="+frame.jpegSize+" Status="+frame.statusSize);first=false;}
                                int[] raw=frame.thermal();int[] ordered=raw.clone();Arrays.sort(ordered);
                                int span=ordered[18816]-ordered[384];
                                if(now>=cooldown&&lastSpan>=120&&span<Math.max(45,lastSpan*.28)){skip=6;cooldown=now+8000;continue;}
                                if(skip>0){if(--skip==0)lastSpan=span;continue;}
                                lastSpan=span;
                                if(running)listener.frame(raw,System.currentTimeMillis(),frame.jpeg(),frame.status());
                            }
                        }
                        if(now-lastFrame>3000){
                            if(++restarts>2)throw new IOException("Frame stream stalled; reopening session");
                            message("Recovering frame stream ("+restarts+"/2)");
                            alt(v0);if(restarts==2)alt(f0);SystemClock.sleep(50);if(restarts==2)alt(f1);alt(v1);
                            connection.controlTransfer(2,1,0,0x85,null,0,200);frames.clear();lastFrame=now;
                        }
                    }else if(now-start>20000)throw new IOException("iAP2 handshake timed out");
                    session.tick(now-start);
                    int n=connection.bulkTransfer(input,cb,cb.length,session.streaming()?1:100);
                    if(n>0){links.add(cb,n);List<byte[]> batch=new ArrayList<>();byte[] p;
                        while((p=links.pop())!=null)batch.add(p);
                        int last=-1;for(int i=0;i<batch.size();i++)if(batch.get(i).length>10)last=i;
                        for(int i=0;i<batch.size();i++)session.accept(batch.get(i),i==last);
                    }
                }
            }catch(Exception e){message("USB: "+e.getMessage()+" — reconnecting");}
            finally{UsbDeviceConnection c=connection;connection=null;if(c!=null){
                try{c.releaseInterface(v0);c.releaseInterface(f0);c.releaseInterface(c0);}catch(Exception ignored){}c.close();}}
            if(running){if(!manager.getDeviceList().containsKey(device.getDeviceName())){message("Camera disconnected");break;}SystemClock.sleep(500);}
        }
        running=false;
    }
}
