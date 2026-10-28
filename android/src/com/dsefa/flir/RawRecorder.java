package com.dsefa.flir;
import java.io.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Bounded disk queue: USB never waits for storage. */
public final class RawRecorder implements AutoCloseable {
    private final ArrayBlockingQueue<RawArchive.Sample> queue=new ArrayBlockingQueue<>(64);
    private volatile boolean running=true;
    private final CountDownLatch completed=new CountDownLatch(1);
    public RawRecorder(File file,Consumer<String> error)throws IOException{
        this(file,error,null,Long.MAX_VALUE);
    }
    public RawRecorder(File file,Consumer<String> error,StorageBudget budget,long segmentBytes)throws IOException{
        if(!file.createNewFile())throw new IOException("Archive already exists; refusing to overwrite");
        if(budget!=null)try{budget.open(file);budget.reserve(file,4);}catch(IOException e){budget.release(file);throw e;}
        new Thread(()->{
            File current=file;RawArchive.Writer writer=null;long bytes=4;int part=0;
            try{
                writer=new RawArchive.Writer(new FileOutputStream(current));
                while(running||!queue.isEmpty()){
                    RawArchive.Sample s=queue.poll(100,TimeUnit.MILLISECONDS);
                    if(s!=null){long frameBytes=12+2L*s.raw.length;
                        if(bytes+frameBytes>segmentBytes&&bytes>4){writer.close();writer=null;if(budget!=null)budget.release(current);
                            String stem=file.getName().substring(0,file.getName().length()-6);
                            current=new File(file.getParentFile(),stem+String.format(java.util.Locale.US,"_part-%04d.f1raw",++part));
                            if(!current.createNewFile())throw new IOException("Segment already exists; refusing to overwrite");
                            if(budget!=null){budget.open(current);budget.reserve(current,4);}writer=new RawArchive.Writer(new FileOutputStream(current));bytes=4;
                        }
                        if(budget!=null)budget.reserve(current,frameBytes);writer.write(s.timestamp,s.raw);bytes+=frameBytes;
                    }
                }
            }catch(Exception e){running=false;error.accept("Recording: "+e.getMessage());}
            finally{queue.clear();if(writer!=null)try{writer.close();}catch(IOException e){error.accept("Recording finalization: "+e.getMessage());}
                if(budget!=null)budget.release(current);completed.countDown();}
        },"FLIR RAW writer").start();
    }
    public synchronized boolean offer(int[] raw,long timestamp){if(!running)return false;
        RawArchive.Sample s=new RawArchive.Sample();s.raw=raw;s.timestamp=timestamp;return queue.offer(s);}
    public synchronized void close(){running=false;}
    public boolean complete(){return completed.getCount()==0;}
    public boolean awaitComplete(long milliseconds)throws InterruptedException{return completed.await(milliseconds,TimeUnit.MILLISECONDS);}
}
