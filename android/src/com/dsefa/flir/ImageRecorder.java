package com.dsefa.flir;

import java.io.*;
import java.util.Locale;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** A three-frame, nonblocking queue with a single segmented image writer and a 1fps source gate. */
public final class ImageRecorder implements AutoCloseable {
    public static final long DEFAULT_SEGMENT_BYTES=16L*1024*1024;
    private final ArrayBlockingQueue<ImageClip.Sample> queue=new ArrayBlockingQueue<>(3);
    private final CountDownLatch completed=new CountDownLatch(1);
    private volatile boolean running=true;
    private final long segmentBytes;
    private boolean hasAccepted;
    private long lastAccepted;

    public ImageRecorder(File file,Consumer<String> error,StorageBudget budget,long segmentBytes)throws IOException {
        if(file==null||error==null)throw new IllegalArgumentException("File and error callback are required");
        if(segmentBytes<17)throw new IllegalArgumentException("Clip segment cannot hold a frame");
        this.segmentBytes=Math.min(DEFAULT_SEGMENT_BYTES,segmentBytes);
        if(!file.createNewFile())throw new IOException("Image clip already exists; refusing to overwrite");
        if(budget!=null)try {budget.open(file);budget.reserve(file,4);}
        catch(IOException failure){budget.release(file);file.delete();throw failure;}
        Thread worker=new Thread(()->write(file,error,budget),"FLIR image writer");
        worker.start();
    }
    public ImageRecorder(File file,Consumer<String> error)throws IOException {this(file,error,null,DEFAULT_SEGMENT_BYTES);}
    private void write(File file,Consumer<String> error,StorageBudget budget) {
        File current=file;ImageClip.Writer writer=null;long bytes=4;int part=0,frames=0;
        try {
            writer=new ImageClip.Writer(new FileOutputStream(current));
            while(running||!queue.isEmpty()) {
                ImageClip.Sample sample=queue.poll(100,TimeUnit.MILLISECONDS);
                if(sample==null)continue;
                long frameBytes=12L+sample.jpeg.length;
                if(bytes+frameBytes>segmentBytes) {
                    writer.close();writer=null;
                    if(budget!=null)budget.release(current);
                    String name=file.getName(),stem=name.endsWith(".f1clip")?name.substring(0,name.length()-7):name;
                    File next=new File(file.getParentFile(),stem+String.format(Locale.US,"_part-%04d.f1clip",++part));
                    if(!next.createNewFile())throw new IOException("Image segment already exists; refusing to overwrite");
                    current=next;bytes=4;frames=0;
                    if(budget!=null){budget.open(current);budget.reserve(current,4);}
                    writer=new ImageClip.Writer(new FileOutputStream(current));
                }
                if(budget!=null)budget.reserve(current,frameBytes);
                writer.write(sample.timestamp,sample.jpeg);bytes+=frameBytes;frames++;
            }
        } catch(Exception failure) {running=false;report(error,"Image recording: "+failure.getMessage());}
        finally {
            running=false;queue.clear();
            if(writer!=null)try {writer.close();}catch(IOException failure){report(error,"Image finalization: "+failure.getMessage());}
            if(budget!=null)budget.release(current);
            if(frames==0)current.delete();
            completed.countDown();
        }
    }
    private static void report(Consumer<String> callback,String message){try {callback.accept(message);}catch(RuntimeException ignored){}}
    public synchronized boolean offer(byte[] jpeg,long timestamp) {
        if(!running||jpeg==null||jpeg.length==0||jpeg.length>ImageClip.MAX_JPEG_BYTES||16L+jpeg.length>segmentBytes)return false;
        if(hasAccepted&&(timestamp<lastAccepted||Long.compareUnsigned(timestamp-lastAccepted,1000L)<0))return false;
        if(queue.remainingCapacity()==0)return false;
        ImageClip.Sample sample=new ImageClip.Sample();sample.timestamp=timestamp;sample.jpeg=jpeg.clone();
        if(!queue.offer(sample))return false;
        hasAccepted=true;lastAccepted=timestamp;return true;
    }
    public synchronized void close(){running=false;}
    public boolean complete(){return completed.getCount()==0;}
    public boolean awaitComplete(long milliseconds)throws InterruptedException{return completed.await(milliseconds,TimeUnit.MILLISECONDS);}
}
